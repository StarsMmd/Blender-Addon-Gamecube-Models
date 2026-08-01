"""Phase 3 (export) — synthesize GPT1 file bytes from a semantic IRParticleSystem.

The inverse of the import-side summarizer: over-life curves, birth state,
forces, and texture-sheet animation are compiled back into generator
bytecode (via `shared.helpers.gpt1_commands.assemble`), texture pixels are
re-encoded to a GX format, and the container is emitted through
`shared.helpers.gpt1.GPT1File.to_bytes`. Synthesis is semantic, not
byte-reproducing: a fresh instruction stream is generated from the curves.
"""
import struct

try:
    from .....shared.helpers.gpt1 import (
        GPT1File, PTLSection, TXGSection, GeneratorDef, TextureContainer,
    )
    from .....shared.helpers.gpt1_commands import assemble, ParticleInstruction
    from .....shared.helpers.scale import METERS_TO_GC, GC_TO_METERS
    from .....shared.texture_encoder import encode_texture
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.gpt1 import (
        GPT1File, PTLSection, TXGSection, GeneratorDef, TextureContainer,
    )
    from shared.helpers.gpt1_commands import assemble, ParticleInstruction
    from shared.helpers.scale import METERS_TO_GC, GC_TO_METERS
    from shared.texture_encoder import encode_texture
    from shared.helpers.logger import StubLogger


# GX format used for re-encoded particle textures. RGB5A3 carries alpha at
# half the size of RGBA8; particle sheets are small so quality loss is minor.
_PARTICLE_TEXTURE_FORMAT = 0x5

# Header defaults for synthesized generators — these header fields are not
# decoded by any known consumer, so fresh exports write the values that
# dominate game-native archives.
_DEFAULT_GEN_TYPE = 5
_DEFAULT_GEN_FLAGS = 0x1400001

# Bytecode field limits: LIFETIME waits are 13-bit, tween times 15-bit,
# kill-timer fields u16.
_MAX_LIFETIME_FRAMES = 0x1FFF
_MAX_TIME = 0x7FFF
_MAX_U16 = 0xFFFF


def compose_particles(ir_particles, logger=StubLogger()):
    """Convert a semantic IRParticleSystem into GPT1 file bytes.

    In: ir_particles (IRParticleSystem|None); logger (Logger).
    Out: bytes — the raw GPT1 file, or empty bytes when there are no emitters.
    """
    if ir_particles is None or not ir_particles.emitters:
        return b''

    # Textures that will re-encode to an intensity format — selecting one at
    # runtime implies additive blending, so those emitters need no blend bits.
    intensity_textures = {
        i for i, tex in enumerate(ir_particles.textures)
        if tex.pixels and _pick_particle_format(tex.pixels) == 0x1
    }

    generators = []
    for emitter in ir_particles.emitters:
        generators.append(_synthesize_generator(emitter, intensity_textures, logger))

    ptl = PTLSection(
        version=0x43,
        unknown_02=0,
        skip_sections=0,
        generators=generators,
    )

    # Build texture containers — one per IRParticleTexture for simplicity.
    containers = []
    tex_data_parts = []
    tex_data_cursor = 0
    # data_offset is stored relative to the TEX region here and rebased to
    # absolute (from GPT1 start) after serialization — see _fix_data_offsets.
    for tex in ir_particles.textures:
        encoded, fmt = _encode_ir_texture(tex)
        containers.append(TextureContainer(
            nb_textures=1,
            format=fmt,
            data_offset=tex_data_cursor,  # relative offset into TEX region
            width=int(tex.width),
            height=int(tex.height),
            nb_mipmaps=0,
            texture_offsets=[0],
        ))
        tex_data_parts.append(encoded)
        tex_data_cursor += len(encoded)

    txg = TXGSection(containers=containers)
    tex_data = b''.join(tex_data_parts)

    gpt1 = GPT1File(
        ptl=ptl,
        txg=txg,
        tex_data=tex_data,
        ref_ids=list(range(len(generators))),  # identity — one REF per emitter
    )

    blob = gpt1.to_bytes()
    blob = _fix_data_offsets(blob, gpt1)

    logger.info("  Composed GPT1: %d emitters, %d textures, %d bytes",
                len(generators), len(containers), len(blob))
    return blob


# ---------------------------------------------------------------------------
# Generator synthesis
# ---------------------------------------------------------------------------


def _synthesize_generator(emitter, intensity_textures, logger):
    """Compile one IRParticleEmitter into a GeneratorDef with fresh bytecode.

    In: emitter (IRParticleEmitter); intensity_textures (set[int], texture
        indices that re-encode to an intensity format); logger (Logger).
    Out: GeneratorDef.
    """
    ops = []
    ops.extend(_render_state_ops(emitter))
    ops.extend(_birth_ops(emitter))
    if emitter.looping:
        ops.append(_ins('SAVE_JUMP', {}))
    ops.extend(_timeline_ops(emitter))
    ops.append(_ins('JUMP' if emitter.looping else 'EXIT', {}))

    return GeneratorDef(
        gen_type=_synthesize_gen_type(emitter.emission.shape),
        unknown_02=0,
        lifetime=max(0, int(round(emitter.emit_duration))),
        max_particles=int(emitter.max_particles),
        flags=_synthesize_flags(emitter, intensity_textures),
        params=_synthesize_params(emitter),
        command_bytes=assemble(ops),
    )


def _ins(mnemonic, args):
    """Build a ParticleInstruction for the assembler (offsets/raw unused)."""
    return ParticleInstruction(offset=0, opcode=0, mnemonic=mnemonic, args=args)


def _to_gc(value):
    """Metres → source units, preferring the f32 that inverts exactly.

    The unit factor is not a binary power, so naive multiply-then-round can
    land one ULP off the stored value the import scaled from. Testing the
    rounded candidate and its two f32 neighbours for an exact inverse
    recovers the original bit pattern whenever one exists.

    In: value (float, metres).
    Out: float — a value that survives ``struct.pack('>f', ...)``.
    """
    base = struct.unpack('>f', struct.pack('>f', value * METERS_TO_GC))[0]
    bits = struct.unpack('>I', struct.pack('>f', base))[0]
    for candidate_bits in (bits, bits + 1, bits - 1):
        candidate = struct.unpack('>f', struct.pack('>I', candidate_bits & 0xFFFFFFFF))[0]
        if candidate * GC_TO_METERS == value:
            return candidate
    return base


def _render_state_ops(emitter):
    """Emit render/texture-sampling state opcodes (stream head).

    In: emitter (IRParticleEmitter).
    Out: list[ParticleInstruction].
    """
    ops = []
    render, texture = emitter.render, emitter.texture
    if not render.textured:
        ops.append(_ins('TEX_OFF', {}))
    if render.billboard == 'VELOCITY_STRETCH':
        ops.append(_ins('DIRVEC_ON', {}))
    if not render.depth_test:
        ops.append(_ins('NO_ZCOMP', {}))
    if render.trail_length > 0:
        ops.append(_ins('SET_TRAIL', {'length': render.trail_length * METERS_TO_GC}))
    if texture.filter == 'NEAREST':
        ops.append(_ins('TEXINTERP_NEAR', {}))
    if texture.wrap_s == 'MIRROR' and texture.wrap_t == 'MIRROR':
        ops.append(_ins('MIRROR_ST', {}))
    elif texture.wrap_s == 'MIRROR':
        ops.append(_ins('MIRROR_S', {}))
    elif texture.wrap_t == 'MIRROR':
        ops.append(_ins('MIRROR_T', {}))
    return ops


def _birth_ops(emitter):
    """Emit birth-time initializer opcodes (before the first LIFETIME).

    In: emitter (IRParticleEmitter).
    Out: list[ParticleInstruction].
    """
    ops = []
    birth, rotation, forces = emitter.birth, emitter.rotation, emitter.forces
    life = emitter.particle_lifetime

    if life.spread > 0:
        rng = min(_MAX_U16, int(round(life.spread * 2)))
        base = min(_MAX_U16, max(0, int(round(life.base - life.spread))))
        ops.append(_ins('RAND_KILL_TIMER', {'base': base, 'range': rng}))

    pos_args = _axis_args(birth.position.base, METERS_TO_GC)
    if pos_args:
        ops.append(_ins('SET_POS', pos_args))
    if any(birth.position.spread):
        ops.append(_ins('RAND_OFFSET', {
            axis: birth.position.spread[i] * METERS_TO_GC
            for i, axis in enumerate(('x', 'y', 'z'))}))

    vel_args = _axis_args(birth.velocity.base, METERS_TO_GC)
    if vel_args:
        ops.append(_ins('SET_VEL', vel_args))

    # The header's initial-scale slot carries the base size, so plain sizes
    # need no opcode; a randomized size re-rolls at birth over
    # [base - spread, base + spread] — SCALE_RAND's [base, base + range] form.
    if birth.size.spread > 0:
        size_low = _to_gc(birth.size.base - birth.size.spread)
        ops.append(_ins('SCALE_RAND', {'time': 0, 'base': size_low,
                                       'range': _to_gc(birth.size.spread * 2)}))

    if rotation.initial.base != 0.0 or rotation.initial.spread != 0.0:
        ops.append(_ins('RAND_ROTATE', {
            'base': rotation.initial.base - rotation.initial.spread,
            'range': rotation.initial.spread * 2,
            'param': 0}))
    spin_window = min(_MAX_TIME, max(1, int(round(life.base))))
    if rotation.accel != 0.0:
        ops.append(_ins('ROTATE_ACCEL', {
            'direction': 1 if rotation.rate.base < 0 else 0,
            'rate': abs(rotation.rate.base),
            'accel': rotation.accel,
            'time': spin_window}))
    elif rotation.rate.base != 0.0:
        ops.append(_ins('ROTATE_RAND', {
            'time': spin_window,
            'value': rotation.rate.base}))

    if any(c > 0 for c in birth.color_spread):
        ops.append(_ins('RAND_PRIMCOL', {
            c: int(round(birth.color_spread[i] * 255))
            for i, c in enumerate(('r', 'g', 'b', 'a'))}))

    # Gravity and friction ride the header's initial-value slots
    # (params[0] / params[1]) rather than bytecode ops — matching how the
    # game archives author them.

    return ops


def _timeline_ops(emitter):
    """Compile over-life curves into a LIFETIME-gapped opcode timeline.

    Each curve segment becomes an interpolating opcode fired at its start
    key's frame with a tween equal to the segment length; LIFETIME (or
    LIFETIME_TEX, when a flip-book frame starts there) advances the cursor
    between event frames.

    In: emitter (IRParticleEmitter).
    Out: list[ParticleInstruction].
    """
    total = max(0, int(round(emitter.particle_lifetime.base)))
    if total == 0:
        return []

    def to_frame(age):
        return max(0, min(total, int(round(age * total))))

    # (frame, ordered op) events. Ramp ops fire at the *previous* key's frame.
    events = []

    # Flat segments need no opcode: a hold is implicit in the stream (the
    # decoder re-anchors it from the gap before the next ramp), and emitting
    # one would re-quantize a derived hold value the source never stored.
    stops = emitter.color_over_life
    for prev, stop in zip(stops, stops[1:]):
        if stop.rgba == prev.rgba:
            continue
        f_prev, f_cur = to_frame(prev.age), to_frame(stop.age)
        events.append((f_prev, _ins('SET_PRIMCOL', {
            'time': min(_MAX_TIME, max(0, f_cur - f_prev)),
            **{c: int(round(stop.rgba[i] * 255))
               for i, c in enumerate(('r', 'g', 'b', 'a'))}})))
    if stops and to_frame(stops[0].age) == 0 and stops[0].rgba != (1.0, 1.0, 1.0, 1.0):
        events.insert(0, (0, _ins('SET_PRIMCOL', {
            'time': 0,
            **{c: int(round(stops[0].rgba[i] * 255))
               for i, c in enumerate(('r', 'g', 'b', 'a'))}})))

    keys = emitter.size_over_life
    for prev, key in zip(keys, keys[1:]):
        if key.value == prev.value:
            continue
        f_prev, f_cur = to_frame(prev.age), to_frame(key.age)
        events.append((f_prev, _ins('SCALE', {
            'time': min(_MAX_TIME, max(0, f_cur - f_prev)),
            'target': _to_gc(key.value)})))

    for sub in emitter.sub_emitters:
        if sub.emitter_ref < 0:
            continue
        mnemonic = 'SPAWN_PARTICLE_VEL' if sub.inherit_velocity else 'SPAWN_GENERATOR'
        for _ in range(max(1, sub.count)):
            events.append((to_frame(sub.age), _ins(mnemonic, {'id': sub.emitter_ref})))

    # Flip-book frames are cursor advances themselves — indexed separately.
    # Same-frame collisions keep the last entry (only that one displays).
    tex_by_frame = {}
    for idx, age in zip(emitter.texture.frames, emitter.texture.frame_ages):
        tex_by_frame[to_frame(age)] = int(idx)

    events.sort(key=lambda e: e[0])

    # Walk the merged timeline: advance the cursor with LIFETIME(_TEX) gaps,
    # emitting each event's op once the cursor reaches its frame.
    cursor_points = sorted(set([f for f, _ in events]) | set(tex_by_frame) | {total})
    ops = []
    cursor = 0
    event_i = 0
    for point in cursor_points:
        gap = point - cursor
        if gap > 0:
            _emit_gap(ops, gap, tex_by_frame.get(cursor))
            cursor = point
        while event_i < len(events) and events[event_i][0] <= cursor:
            ops.append(events[event_i][1])
            event_i += 1
    # A flip-book frame starting at the very end has no gap to ride on.
    if total in tex_by_frame and cursor >= total:
        ops.append(_ins('LIFETIME_TEX', {'frames': 0, 'texture': tex_by_frame[total]}))

    return ops


def _emit_gap(ops, gap, tex_index):
    """Advance the age cursor by `gap` frames, splitting past the 13-bit limit.

    The flip-book frame (when one starts at the gap's beginning) rides on the
    first chunk as LIFETIME_TEX; remainder chunks are plain LIFETIME waits.

    In: ops (list, mutated); gap (int, > 0); tex_index (int|None).
    Out: None.
    """
    first = True
    while gap > 0:
        chunk = min(gap, _MAX_LIFETIME_FRAMES)
        if first and tex_index is not None:
            ops.append(_ins('LIFETIME_TEX', {'frames': chunk, 'texture': tex_index}))
        else:
            ops.append(_ins('LIFETIME', {'frames': chunk}))
        gap -= chunk
        first = False


def _axis_args(vec, scale):
    """Build x/y/z args for an axis-subset opcode, omitting zero axes.

    In: vec (tuple[float,3]); scale (float).
    Out: dict — empty when all components are zero.
    """
    return {axis: vec[i] * scale
            for i, axis in enumerate(('x', 'y', 'z')) if vec[i] != 0.0}


# Semantic blend mode → header flag bits 10-11.
_BLEND_TO_BITS = {'ALPHA': 0, 'ADD': 1, 'SUBTRACT': 2, 'MULTIPLY': 3}



def _synthesize_gen_type(shape):
    """Emission shape → gen_type (mode nibble + preserved renderer bits).

    In: shape (IREmissionShape).
    Out: int.
    """
    if shape.kind == 'BOX':
        mode = 5
    elif shape.kind == 'SPHERE':
        mode = 8
    else:
        mode = 3 if shape.uniform_area else 0
    return (shape.type_flags << 4) | mode


def _synthesize_flags(emitter, intensity_textures):
    """Header flags: carried behaviour bits plus the blend field.

    Additive via an intensity texture needs no flag bits — selecting the
    sheet enables it at runtime whether or not texturing is on — so those
    emitters keep the bits clear like the originals.

    In: emitter (IRParticleEmitter); intensity_textures (set[int]).
    Out: int.
    """
    blend = emitter.render.blend_mode
    if (blend == 'ADD' and emitter.texture.frames
            and emitter.texture.frames[0] in intensity_textures):
        blend = 'ALPHA'
    base = emitter.emission.shape.behaviour_flags or _DEFAULT_GEN_FLAGS
    flags = (base & ~0xC00) | (_BLEND_TO_BITS.get(blend, 0) << 10)
    # Gravity and friction only run when their enable bits are set.
    if emitter.forces.gravity[1] != 0.0:
        flags |= 0x1
    if emitter.forces.drag > 0.0:
        flags |= 0x2
    return flags


def _synthesize_params(emitter):
    """Fill the header params from the emission shape, cadence, and forces.

    Exact inverse of the import-side header decode: the shape's lengths go
    back to source units, angles stay radians, the spawn-rate accumulator
    parameter recovers its sign from the jitter flag, and gravity/friction
    seed the per-particle initial values.

    In: emitter (IRParticleEmitter).
    Out: tuple[float] length 12.
    """
    p = [0.0] * 12
    shape = emitter.emission.shape

    # The runtime subtracts this slot from vel.y each frame, so the stored
    # value is the negated semantic acceleration. (Guarded so a zero stays
    # +0.0 — negating it would flip the sign bit in the file.)
    if emitter.forces.gravity[1] != 0.0:
        p[0] = -emitter.forces.gravity[1] * METERS_TO_GC
    if emitter.forces.drag > 0.0:
        p[1] = 1.0 - emitter.forces.drag
    p[2] = shape.velocity[0] * METERS_TO_GC
    p[3] = shape.velocity[1] * METERS_TO_GC
    p[4] = shape.velocity[2] * METERS_TO_GC
    rate = emitter.emission.rate
    p[7] = rate * 2.0 if emitter.emission.rate_jitter else -rate
    # The initial-scale slot: when the bytecode re-rolls the scale at birth
    # (a spread exists), authors set this to the roll's base — the low end.
    p[8] = _to_gc(emitter.birth.size.base - emitter.birth.size.spread)

    if shape.kind == 'BOX':
        p[9] = shape.box_extents[0] * METERS_TO_GC
        p[10] = shape.box_extents[1] * METERS_TO_GC
        p[11] = shape.box_extents[2] * METERS_TO_GC
    elif shape.kind == 'SPHERE':
        p[5] = -shape.radius * METERS_TO_GC if shape.ring else shape.radius * METERS_TO_GC
        p[9] = shape.radial_speed * METERS_TO_GC
        # The next slot is dead for spheres; archives author it as a copy of
        # the speed, so the copy keeps re-exports byte-identical.
        p[10] = p[9]
        p[11] = shape.polar_max
    else:  # DISC
        p[5] = -shape.radius * METERS_TO_GC if shape.ring else shape.radius * METERS_TO_GC
        p[6] = -shape.cone_angle if shape.sweep else shape.cone_angle
        p[9], p[10] = shape.arc_start, shape.arc_end
    return tuple(p)


# ---------------------------------------------------------------------------
# Texture encoding / container fix-up
# ---------------------------------------------------------------------------


def _encode_ir_texture(tex):
    """Encode IRParticleTexture RGBA pixels into GX-format bytes.

    IR pixels are stored bottom-to-top (matching `decode_texture`'s output
    and Blender's convention). `encode_texture` expects the same order, so
    no flip is needed.

    In: tex (IRParticleTexture).
    Out: bytes.
    """
    if tex.width <= 0 or tex.height <= 0 or not tex.pixels:
        return b'', _PARTICLE_TEXTURE_FORMAT
    fmt = _pick_particle_format(tex.pixels)
    result = encode_texture(tex.pixels, tex.width, tex.height, fmt)
    return bytes(result['image_data']), fmt


def _pick_particle_format(pixels):
    """Choose the GX format a particle sheet re-encodes to.

    Intensity sheets (r == g == b == a everywhere) go back to I8: it is
    what the source archives use, and the runtime keys additive blending
    off the intensity family — an RGB re-encode would silently turn an
    additive sheet alpha-blended in game.

    In: pixels (bytes, RGBA u8).
    Out: int — GX format id.
    """
    view = memoryview(pixels)
    for i in range(0, len(view) - 3, 4):
        r = view[i]
        if view[i + 1] != r or view[i + 2] != r or view[i + 3] != r:
            return _PARTICLE_TEXTURE_FORMAT
    return 0x1  # GX_TF_I8


def _fix_data_offsets(blob, gpt1):
    """Rewrite container data_offsets to be absolute (from GPT1 base).

    GPT1File serialization lays out as [header][PTL][TXG][TEX][REF]. The
    TEX region start in the final blob = len(header) + len(PTL_bytes) +
    len(TXG_bytes). Each container's data_offset currently holds a
    relative-to-TEX-start offset; shift by the absolute TEX start.
    """
    try:
        from .....shared.helpers.binary import read, write_into
        from .....shared.helpers.gpt1 import _HEADER_SIZE, _serialize_ptl, _serialize_txg
    except (ImportError, SystemError):
        from shared.helpers.binary import read, write_into
        from shared.helpers.gpt1 import _HEADER_SIZE, _serialize_ptl, _serialize_txg

    ptl_bytes = _serialize_ptl(gpt1.ptl)
    txg_bytes = _serialize_txg(gpt1.txg)
    ptl_off = _HEADER_SIZE
    txg_off = ptl_off + len(ptl_bytes)
    tex_start = txg_off + len(txg_bytes)

    out = bytearray(blob)
    # Walk the TXG section in the serialized blob and rewrite data_offset fields.
    nb_containers = read('uint', out, txg_off)
    for i in range(nb_containers):
        ptr_off = txg_off + 4 + i * 4
        container_rel = read('uint', out, ptr_off)
        if container_rel == 0xFFFFFFFF:
            continue
        container_abs = txg_off + container_rel
        current = read('uint', out, container_abs + 8)
        write_into('uint', current + tex_start, out, container_abs + 8)
    return bytes(out)
