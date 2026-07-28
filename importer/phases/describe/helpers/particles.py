"""Phase 4b — Describe Particles: GPT1 binary → semantic IRParticleSystem.

Summarizes each generator's command bytecode into the platform-agnostic
particle vocabulary (birth state, over-life curves, forces, texture-sheet
animation, sub-emitters, render state). The mapping is intentionally lossy:
opcodes with no generic particle-system meaning are dropped with a debug log.

Timing model recovered here: LIFETIME opcodes advance a per-particle age
cursor; every other opcode fires at the current cursor. An interpolating
opcode additionally carries its own tween duration, so its key lands at
cursor + tween and a hold key is inserted when a gap precedes the ramp.
Opcodes before the first LIFETIME are birth-time initializers.
"""
try:
    from .....shared.helpers.gpt1 import GPT1File
    from .....shared.helpers.gpt1_commands import disassemble
    from .....shared.IR.particles import (
        IRRandomScalar, IRRandomVec3, IRColorStop, IRScalarKey,
        IRParticleEmission, IRParticleBirth, IRParticleRotation,
        IRParticleForces, IRParticleTextureAnim, IRParticleRender,
        IRSubEmitter, IRParticleEmitter, IRParticleTexture, IRParticleSystem,
    )
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.scale import GC_TO_METERS
    from .....shared.gx_texture import decode_texture
except (ImportError, SystemError):
    from shared.helpers.gpt1 import GPT1File
    from shared.helpers.gpt1_commands import disassemble
    from shared.IR.particles import (
        IRRandomScalar, IRRandomVec3, IRColorStop, IRScalarKey,
        IRParticleEmission, IRParticleBirth, IRParticleRotation,
        IRParticleForces, IRParticleTextureAnim, IRParticleRender,
        IRSubEmitter, IRParticleEmitter, IRParticleTexture, IRParticleSystem,
    )
    from shared.helpers.logger import StubLogger
    from shared.helpers.scale import GC_TO_METERS
    from shared.gx_texture import decode_texture


# Safety cap on executed instructions per generator (loop unrolling included) —
# guards against malformed streams; real generators run well under this.
_MAX_EXECUTED_OPS = 8192

# Opcodes with no generic particle-system equivalent — skipped with a debug log.
_DROPPED_MNEMONICS = frozenset([
    'MOVE', 'MODIFY_DIR', 'SCALE_VEL', 'SCALE_VEL_AXIS', 'SET_SPEED',
    'ALPHA_CMP', 'FLIP_S', 'FLIP_T', 'TEXEDGE_ON', 'SET_PALETTE',
    'SET_CALLBACK', 'CUSTOM_FLOAT', 'MAT_COLOR', 'AMB_COLOR',
    'GEN_FLAG_2000', 'GEN_FLAG_1000', 'APPLY_APPSRT', 'SET_JOINT',
    'VEL_TO_JOINT', 'FORCES_JOINT', 'GEN_DIR_BASE', 'RAND_ENVCOL',
    'RAND_KILL_CHANCE',
])


def describe_particles(gpt1_data, logger=StubLogger()):
    """Convert raw GPT1 bytes into a semantic IRParticleSystem.

    In: gpt1_data (bytes, may be empty); logger (Logger).
    Out: IRParticleSystem|None — None if data empty or GPT1 parse fails.
    """
    if not gpt1_data:
        return None

    try:
        gpt1 = GPT1File.from_bytes(gpt1_data)
    except ValueError as e:
        logger.info("  Skipping GPT1: %s", e)
        return None

    n_generators = len(gpt1.ptl.generators)
    # global id → local generator index (REF table)
    ref_map = {gid: local for local, gid in enumerate(gpt1.ref_ids)}

    # Convert textures with pixel decoding (first — emitters validate
    # their flip-book frame indices against the texture count)
    textures = []
    for container in gpt1.txg.containers:
        for t_idx in range(container.nb_textures):
            pixels = _decode_particle_texture(
                gpt1_data, container.format, container.width, container.height,
                container.data_offset, container.texture_offsets, t_idx, logger)
            textures.append(IRParticleTexture(
                width=container.width,
                height=container.height,
                pixels=pixels,
            ))

    emitters = []
    for i, gen in enumerate(gpt1.ptl.generators):
        emitter = _summarize_generator(gen, i, ref_map, n_generators,
                                       len(textures), logger)
        emitters.append(emitter)

    logger.info("  Particles: %d emitters, %d textures described",
                len(emitters), len(textures))

    return IRParticleSystem(emitters=emitters, textures=textures)


def particle_ref_map(gpt1_data):
    """Read the REF table as a global-generator-id → local-emitter-index map.

    Used by the animation decoder to resolve particle-spawn track values
    (which carry global ids) to indices into IRParticleSystem.emitters.

    In: gpt1_data (bytes, may be empty).
    Out: dict[int, int] — empty if the data is missing or unparsable.
    """
    if not gpt1_data:
        return {}
    try:
        gpt1 = GPT1File.from_bytes(gpt1_data)
    except ValueError:
        return {}
    return {gid: local for local, gid in enumerate(gpt1.ref_ids)}


# ---------------------------------------------------------------------------
# Generator summarizer
# ---------------------------------------------------------------------------


def _summarize_generator(gen, index, ref_map, n_generators, n_textures, logger):
    """Summarize one generator's header + bytecode into an IRParticleEmitter.

    In: gen (GeneratorDef); index (int); ref_map (dict[int,int], global→local);
        n_generators (int); n_textures (int); logger (Logger).
    Out: IRParticleEmitter.
    """
    executed, looping = _walk_instructions(disassemble(gen.command_bytes))

    birth = IRParticleBirth()
    rotation = IRParticleRotation()
    forces = IRParticleForces()
    render = IRParticleRender()
    texture = IRParticleTextureAnim()

    cursor = 0                    # per-particle age, frames
    birth_phase = True
    prim = (1.0, 1.0, 1.0, 1.0)   # particle color starts white opaque
    env = (0.0, 0.0, 0.0, 0.0)
    size_val = 1.0
    color_stops = []              # (frame, rgba)
    env_stops = []                # (frame, rgba)
    size_keys = []                # (frame, value)
    tex_frames = []               # (frame, texture index)
    subs = []                     # (frame, local emitter index, inherit_velocity)
    primenv_on = False
    kill_base = 0
    kill_spread = 0.0
    dropped = {}

    for ins in executed:
        m = ins.mnemonic
        a = ins.args

        if m in ('LIFETIME', 'LIFETIME_TEX'):
            if m == 'LIFETIME_TEX':
                tex_frames.append((cursor, int(a.get('texture', 0))))
            frames = int(a.get('frames', 0))
            cursor += frames
            # Only a cursor-advancing wait ends the birth phase — zero-frame
            # LIFETIME_TEX at the stream head is just the initial frame select.
            if frames > 0:
                birth_phase = False

        elif m == 'SET_POS':
            if birth_phase:
                birth.position.base = _merge_axes(birth.position.base, a, GC_TO_METERS)
            else:
                dropped[m] = dropped.get(m, 0) + 1

        elif m == 'SET_VEL':
            if birth_phase:
                birth.velocity.base = _merge_axes(birth.velocity.base, a, GC_TO_METERS)
            else:
                dropped[m] = dropped.get(m, 0) + 1

        elif m == 'ACCEL':
            if birth_phase:
                birth.velocity.base = _merge_axes(birth.velocity.base, a, GC_TO_METERS, add=True)
            else:
                dropped[m] = dropped.get(m, 0) + 1

        elif m == 'RAND_OFFSET':
            birth.position.spread = tuple(
                max(s, abs(a.get(axis, 0.0)) * GC_TO_METERS)
                for s, axis in zip(birth.position.spread, ('x', 'y', 'z')))

        elif m == 'SCALE':
            tween = int(a.get('time', 0))
            target = float(a.get('target', 0.0))
            if birth_phase and tween == 0:
                birth.size.base = target
            else:
                _append_key(size_keys, cursor, tween, target, size_val)
            size_val = target

        elif m == 'SCALE_RAND':
            tween = int(a.get('time', 0))
            rng = float(a.get('range', 0.0))
            if birth_phase and tween == 0:
                # target = size + uniform[0, range] → base+spread form
                birth.size = IRRandomScalar(base=size_val + rng / 2.0, spread=abs(rng) / 2.0)
                size_val = birth.size.base
            else:
                # Randomized ramp target approximated by its midpoint.
                target = size_val + rng / 2.0
                _append_key(size_keys, cursor, tween, target, size_val)
                size_val = target

        elif m == 'SET_PRIMCOL':
            prim = _apply_color_op(color_stops, cursor, a, prim)

        elif m == 'SET_ENVCOL':
            env = _apply_color_op(env_stops, cursor, a, env)

        elif m == 'PRIMENV_ON':
            primenv_on = True

        elif m == 'GRAVITY':
            forces.gravity = (0.0, float(a.get('value', 0.0)) * GC_TO_METERS, 0.0)

        elif m == 'FRICTION':
            forces.drag = 1.0 - float(a.get('value', 1.0))

        elif m == 'ROTATE_RAND':
            # Constant angular velocity applied over a window — approximated
            # as the particle's spin rate (window length folded away).
            rotation.rate = IRRandomScalar(base=float(a.get('value', 0.0)))

        elif m == 'ROTATE_ACCEL':
            sign = -1.0 if int(a.get('direction', 0)) else 1.0
            rotation.rate = IRRandomScalar(base=sign * float(a.get('rate', 0.0)))
            rotation.accel = float(a.get('accel', 0.0))

        elif m == 'RAND_ROTATE':
            base = float(a.get('base', 0.0))
            rng = float(a.get('range', 0.0))
            rotation.initial = IRRandomScalar(base=base + rng / 2.0, spread=abs(rng) / 2.0)

        elif m in ('RAND_PRIMCOL', 'RAND_COLORS'):
            birth.color_spread = tuple(
                int(a.get(c, 0)) / 255.0 for c in ('r', 'g', 'b', 'a'))

        elif m == 'RAND_PRIMENV':
            birth.color_spread = tuple(
                int(a.get(c + '_delta', 0)) / 255.0 for c in ('r', 'g', 'b', 'a'))

        elif m == 'RAND_KILL_TIMER':
            base = int(a.get('base', 0))
            rng = int(a.get('range', 0))
            kill_base = base + rng // 2
            kill_spread = rng / 2.0

        elif m in ('SPAWN_GENERATOR', 'SPAWN_PARTICLE', 'SPAWN_PARTICLE_VEL',
                   'SPAWN_GEN_FLAGS'):
            _append_sub(subs, cursor, a.get('id', 0), m.endswith('_VEL'),
                        ref_map, n_generators, dropped, m)

        elif m in ('SPAWN_PARTICLE_REF', 'SPAWN_PARTICLE_REF_VEL',
                   'SPAWN_GEN_REF_FLAGS'):
            _append_sub(subs, cursor, a.get('ref', 0), m.endswith('_VEL'),
                        ref_map, n_generators, dropped, m)

        elif m == 'SPAWN_RAND_REF':
            # Random pick from a ref range — approximated by the range base.
            _append_sub(subs, cursor, a.get('base', 0), False,
                        ref_map, n_generators, dropped, m)

        elif m == 'SET_TEXTURE_IDX':
            if not tex_frames:
                tex_frames.append((cursor, int(a.get('base', 0))))

        elif m == 'TEX_OFF':
            render.textured = False

        elif m == 'DIRVEC_ON':
            render.billboard = 'VELOCITY_STRETCH'
        elif m == 'DIRVEC_OFF':
            render.billboard = 'CAMERA'

        elif m == 'NO_ZCOMP':
            render.depth_test = False

        elif m == 'TEXINTERP_NEAR':
            texture.filter = 'NEAREST'
        elif m == 'TEXINTERP_LINEAR':
            texture.filter = 'LINEAR'

        elif m == 'MIRROR_S':
            texture.wrap_s = 'MIRROR'
        elif m == 'MIRROR_T':
            texture.wrap_t = 'MIRROR'
        elif m == 'MIRROR_ST':
            texture.wrap_s = texture.wrap_t = 'MIRROR'
        elif m == 'MIRROR_OFF':
            texture.wrap_s = texture.wrap_t = 'CLAMP'

        elif m == 'SET_TRAIL':
            render.trail_length = float(a.get('length', 0.0)) * GC_TO_METERS

        elif m in ('LOOP_START', 'LOOP_END', 'SAVE_JUMP', 'JUMP', 'EXIT'):
            pass  # consumed by the walker

        else:
            dropped[m] = dropped.get(m, 0) + 1

    # --- finalize ------------------------------------------------------------

    total = cursor
    if total <= 0 and kill_base:
        total = kill_base
    lifetime = IRRandomScalar(base=float(total), spread=kill_spread)

    _apply_params_heuristic(gen.params, birth, forces)

    color_over_life = _finalize_stops(color_stops, total, initial=(1.0, 1.0, 1.0, 1.0))
    if primenv_on and env_stops:
        env_over_life = _finalize_stops(env_stops, total, initial=(0.0, 0.0, 0.0, 0.0))
        color_over_life = _composite_gradients(color_over_life, env_over_life)

    size_over_life = _finalize_keys(size_keys, total, initial=birth.size.base)

    if tex_frames:
        # Frame indices must land inside the system's texture list; out-of-range
        # indices (observed in some archives) carry unknown flag bits — dropped.
        valid = [(f, idx) for f, idx in tex_frames if 0 <= idx < n_textures]
        if len(valid) != len(tex_frames):
            dropped['LIFETIME_TEX(oob)'] = len(tex_frames) - len(valid)
        # Collapse zero-duration flips: several frame selects at the same
        # instant only display the last one.
        by_frame = {}
        for f, idx in valid:
            by_frame[f] = idx
        texture.frames = tuple(by_frame[f] for f in sorted(by_frame))
        texture.frame_ages = tuple(_norm(f, total) for f in sorted(by_frame))

    sub_emitters = [
        IRSubEmitter(age=_norm(f, total), emitter_ref=ref, count=1, inherit_velocity=inh)
        for f, ref, inh in subs
    ]

    emit_duration = float(gen.lifetime) if gen.lifetime else 120.0
    emission = IRParticleEmission(
        rate=(gen.max_particles / emit_duration) if emit_duration > 0 else 0.0)

    if dropped:
        logger.debug("    Emitter %d: dropped opcodes with no generic equivalent: %s",
                     index, dropped)

    return IRParticleEmitter(
        name="G%02d" % index,
        emit_duration=emit_duration,
        max_particles=int(gen.max_particles),
        particle_lifetime=lifetime,
        looping=looping,
        emission=emission,
        birth=birth,
        color_over_life=color_over_life,
        size_over_life=size_over_life,
        rotation=rotation,
        forces=forces,
        texture=texture,
        render=render,
        sub_emitters=sub_emitters,
    )


def _walk_instructions(instructions):
    """Flatten a bytecode stream into execution order.

    Unrolls bounded LOOP_START/LOOP_END spans; a JUMP back-edge means the
    per-particle animation cycles forever, so the cycle body is kept once
    and the emitter is flagged as looping.

    In: instructions (list[ParticleInstruction]).
    Out: tuple (executed: list[ParticleInstruction], looping: bool).
    """
    out = []
    i = 0
    loop_stack = []   # [start_index_of_body, remaining_iterations]
    looping = False
    while i < len(instructions) and len(out) < _MAX_EXECUTED_OPS:
        ins = instructions[i]
        m = ins.mnemonic
        out.append(ins)
        if m == 'LOOP_START':
            loop_stack.append([i + 1, int(ins.args.get('count', 0))])
        elif m == 'LOOP_END' and loop_stack:
            top = loop_stack[-1]
            top[1] -= 1
            if top[1] > 0:
                i = top[0]
                continue
            loop_stack.pop()
        elif m == 'JUMP':
            looping = True
            break
        elif m == 'EXIT':
            break
        i += 1
    return out, looping


# ---------------------------------------------------------------------------
# Summarizer helpers
# ---------------------------------------------------------------------------


def _merge_axes(base, args, scale, add=False):
    """Merge axis-subset opcode args into a base vector (set or accumulate).

    In: base (tuple[float,3]); args (dict with optional x/y/z); scale (float);
        add (bool — accumulate instead of overwrite).
    Out: tuple[float,3].
    """
    out = list(base)
    for i, axis in enumerate(('x', 'y', 'z')):
        if axis in args:
            v = float(args[axis]) * scale
            out[i] = out[i] + v if add else v
    return tuple(out)


def _append_key(keys, cursor, tween, target, current):
    """Append an over-life curve key, inserting a hold key across any gap.

    A pending key beyond the cursor means the previous ramp was still running
    when this op fired — the source interpreter snaps it complete, so the
    pending key is re-anchored to the current cursor.

    In: keys (list[(frame, value)], mutated); cursor (int, frames); tween (int,
        frames the ramp runs); target (float); current (float, value before ramp).
    Out: None.
    """
    if keys and keys[-1][0] > cursor:
        keys[-1] = (cursor, keys[-1][1])
    elif keys and keys[-1][0] < cursor:
        keys.append((cursor, current))
    elif not keys and cursor > 0:
        keys.append((cursor, current))
    keys.append((cursor + tween, target))


def _apply_color_op(stops, cursor, args, current):
    """Apply a channel-subset color op: record hold + target stops.

    In: stops (list[(frame, rgba)], mutated); cursor (int); args (dict with
        time + optional r/g/b/a u8); current (tuple[float,4], color before).
    Out: tuple[float,4] — the new current color.
    """
    tween = int(args.get('time', 0))
    new = list(current)
    for i, ch in enumerate(('r', 'g', 'b', 'a')):
        if ch in args:
            new[i] = int(args[ch]) / 255.0
    new = tuple(new)
    if stops and stops[-1][0] > cursor:
        # Prior ramp still pending — the source interpreter snaps it complete
        # when a new op fires, so re-anchor its stop to the current cursor.
        stops[-1] = (cursor, stops[-1][1])
    elif stops and stops[-1][0] < cursor:
        stops.append((cursor, current))
    elif not stops and cursor > 0:
        stops.append((cursor, current))
    stops.append((cursor + tween, new))
    return new


def _append_sub(subs, cursor, ref_value, inherit, ref_map, n_generators,
                dropped, mnemonic):
    """Resolve a spawn target to a local emitter index and record the event.

    Resolution: global id via the REF table first, then a plain local index
    if in range; unresolvable targets are dropped.

    In: subs (list, mutated); cursor (int); ref_value (int); inherit (bool);
        ref_map (dict[int,int]); n_generators (int); dropped (dict, mutated);
        mnemonic (str).
    Out: None.
    """
    gid = int(ref_value)
    if gid in ref_map:
        subs.append((cursor, ref_map[gid], inherit))
    elif 0 <= gid < n_generators:
        subs.append((cursor, gid, inherit))
    else:
        dropped[mnemonic] = dropped.get(mnemonic, 0) + 1


def _apply_params_heuristic(params, birth, forces):
    """Map the generator-header shape params onto birth spread / gravity.

    Low-confidence heuristic (the reference interpreter never reads these):
    params[0] doubles as gravity and the emission-mode switch — nonzero means
    velocity-based emission with spread in params[7..9]; zero means
    position-volume emission with radii in params[9..11].

    In: params (tuple[float] length 12); birth (IRParticleBirth, mutated);
        forces (IRParticleForces, mutated).
    Out: None.
    """
    p = tuple(params) + (0.0,) * (12 - len(params)) if params else (0.0,) * 12
    if p[0] != 0.0:
        if forces.gravity == (0.0, 0.0, 0.0):
            forces.gravity = (0.0, p[0] * GC_TO_METERS, 0.0)
        spread = (abs(p[7]) * GC_TO_METERS,
                  abs(p[9]) * GC_TO_METERS,
                  abs(p[8]) * GC_TO_METERS)
        birth.velocity.spread = tuple(
            max(s, n) for s, n in zip(birth.velocity.spread, spread))
    else:
        spread = (abs(p[9]) * GC_TO_METERS,
                  abs(p[10]) * GC_TO_METERS,
                  abs(p[11]) * GC_TO_METERS)
        birth.position.spread = tuple(
            max(s, n) for s, n in zip(birth.position.spread, spread))


def _norm(frame, total):
    """Normalize a frame offset into [0, 1] particle age.

    Clamped: an interpolating opcode's tween runs concurrently with the age
    cursor and may extend past the end of the particle's life.
    """
    return min(1.0, frame / total) if total > 0 else 0.0


def _finalize_stops(stops, total, initial):
    """Normalize (frame, rgba) stops into IRColorStops, anchoring age 0.

    In: stops (list[(frame, rgba)]); total (int, frames); initial (tuple[float,4]).
    Out: list[IRColorStop] (empty if the color never changes).
    """
    if not stops:
        return []
    out = []
    if stops[0][0] > 0:
        out.append(IRColorStop(age=0.0, rgba=initial))
    for frame, rgba in stops:
        out.append(IRColorStop(age=_norm(frame, total), rgba=rgba))
    return out


def _finalize_keys(keys, total, initial):
    """Normalize (frame, value) keys into IRScalarKeys, anchoring age 0.

    In: keys (list[(frame, value)]); total (int); initial (float).
    Out: list[IRScalarKey] (empty if the value never changes).
    """
    if not keys:
        return []
    out = []
    if keys[0][0] > 0:
        out.append(IRScalarKey(age=0.0, value=initial))
    for frame, value in keys:
        out.append(IRScalarKey(age=_norm(frame, total), value=value))
    return out


def _composite_gradients(prim_stops, env_stops):
    """Additively composite two gradients at the union of their stop ages.

    Approximates the source's two-register (primary + environment) color
    blend as a single gradient — used only when the blend is enabled.

    In: prim_stops (list[IRColorStop]); env_stops (list[IRColorStop]).
    Out: list[IRColorStop].
    """
    ages = sorted({s.age for s in prim_stops} | {s.age for s in env_stops})
    out = []
    for age in ages:
        p = _sample_stops(prim_stops, age)
        e = _sample_stops(env_stops, age)
        rgba = tuple(min(1.0, pc + ec) for pc, ec in zip(p, e))
        out.append(IRColorStop(age=age, rgba=rgba))
    return out


def _sample_stops(stops, age):
    """Linearly sample a gradient at a normalized age.

    In: stops (list[IRColorStop], age-ordered, non-empty); age (float).
    Out: tuple[float,4].
    """
    if age <= stops[0].age:
        return stops[0].rgba
    for a, b in zip(stops, stops[1:]):
        if age <= b.age:
            span = b.age - a.age
            t = ((age - a.age) / span) if span > 0 else 1.0
            return tuple(av + (bv - av) * t for av, bv in zip(a.rgba, b.rgba))
    return stops[-1].rgba


# ---------------------------------------------------------------------------
# Texture decoding
# ---------------------------------------------------------------------------


def _decode_particle_texture(gpt1_data, gx_format, width, height,
                              data_offset, texture_offsets, tex_idx, logger):
    """Decode a GX-format particle texture into RGBA pixels via shared decode_texture().

    In: gpt1_data (bytes); gx_format (int, 0x0..0xE); width (int, ≥0, pixels); height (int, ≥0, pixels); data_offset (int, byte offset from GPT1 start); texture_offsets (list[int], TXG-relative); tex_idx (int, ≥0); logger (Logger).
    Out: bytes — RGBA pixels (width*height*4 bytes); empty bytes on unsupported format/oob/decode failure.
    """
    if width == 0 or height == 0:
        return b''

    try:
        from .....shared.gx_texture import FORMAT_INFO
    except (ImportError, SystemError):
        from shared.gx_texture import FORMAT_INFO
    if gx_format not in FORMAT_INFO:
        logger.debug("    Unsupported particle texture format: %d", gx_format)
        return b''

    bpp, tile_w, tile_h, _ = FORMAT_INFO[gx_format]
    blocks_x = (width + tile_w - 1) // tile_w
    blocks_y = (height + tile_h - 1) // tile_h
    tile_bytes = (tile_w * tile_h * bpp) >> 3
    total_bytes = blocks_x * blocks_y * tile_bytes

    tex_start = data_offset
    if tex_idx > 0 and tex_idx < len(texture_offsets):
        tex_start = data_offset + tex_idx * total_bytes

    if tex_start + total_bytes > len(gpt1_data):
        logger.debug("    Particle texture data out of bounds: start=%d, need=%d, have=%d",
                     tex_start, total_bytes, len(gpt1_data))
        return b''

    raw_data = gpt1_data[tex_start:tex_start + total_bytes]
    result = decode_texture(raw_data, width, height, gx_format)
    if result is None:
        return b''
    return bytes(result)
