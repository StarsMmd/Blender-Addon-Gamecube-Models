"""Phase 4 (Export): Package DAT bytes into the final output format.

For .dat output, the DAT bytes are written directly.
For .pkx output:
  - If a PKXHeader was extracted from the Blender scene, builds a new PKX from scratch.
  - Otherwise, if the target file already exists, replaces the DAT in the existing PKX.
  - Shiny parameters are written back if provided.
"""
import os

try:
    from ....shared.helpers.pkx import PKXContainer
    from ....shared.helpers.pkx_header import PKXHeader
    from ....shared.helpers.logger import StubLogger
    from ....shared.helpers.fsys_writer import (
        parse_fsys_summary, find_model_entries, rebuild_fsys_replacing,
        MODEL_TYPE_PKX,
    )
except (ImportError, SystemError):
    from shared.helpers.pkx import PKXContainer
    from shared.helpers.pkx_header import PKXHeader
    from shared.helpers.logger import StubLogger
    from shared.helpers.fsys_writer import (
        parse_fsys_summary, find_model_entries, rebuild_fsys_replacing,
        MODEL_TYPE_PKX,
    )


def package_output(dat_bytes, filepath, options=None, logger=StubLogger(),
                   shiny_params=None, pkx_header=None):
    """Package DAT bytes into the final output format.

    Args:
        dat_bytes: Raw DAT binary from the serialize phase.
        filepath: Target output file path (extension determines format).
        options: dict of exporter options.
        logger: Logger instance.
        shiny_params: ShinyParams from the describe phase, or None.
                      Written into the PKX header when outputting .pkx files.
        pkx_header: PKXHeader from the describe phase, or None.
                    Used to generate PKX files from scratch when present.

    Returns:
        bytes — the final output ready to write to disk.
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 4: Package ===")

    ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''

    if ext == 'pkx':
        final_bytes = _package_pkx(dat_bytes, filepath, shiny_params, pkx_header, logger)
    elif ext == 'fsys':
        final_bytes = _package_fsys(dat_bytes, filepath, shiny_params, pkx_header, logger)
    else:
        final_bytes = dat_bytes

    logger.info("=== Export Phase 4 complete: %d bytes ===", len(final_bytes))
    return final_bytes


def _package_pkx(dat_bytes, filepath, shiny_params, pkx_header, logger):
    """Build or inject PKX output.

    Strategy:
      1. If pkx_header is provided, build from scratch (no existing file needed).
      2. Else if target file exists, inject DAT into existing PKX.
      3. Else build from scratch with default header.

    Args:
        dat_bytes: New DAT binary.
        filepath: Target PKX file path.
        shiny_params: ShinyParams to write, or None.
        pkx_header: PKXHeader from describe phase, or None.
        logger: Logger instance.

    Returns:
        bytes — complete PKX file.
    """
    if pkx_header is not None:
        return _build_pkx_from_header(dat_bytes, pkx_header, shiny_params, logger)
    elif os.path.exists(filepath):
        return _inject_into_existing(dat_bytes, filepath, shiny_params, logger)
    else:
        logger.info("  No PKX metadata and no existing file — generating default XD header")
        default_header = PKXHeader.default_xd()
        return _build_pkx_from_header(dat_bytes, default_header, shiny_params, logger)


def _build_pkx_from_header(dat_bytes, header, shiny_params, logger):
    """Build a PKX file from scratch using a PKXHeader.

    Args:
        dat_bytes: DAT binary.
        header: PKXHeader instance.
        shiny_params: ShinyParams, or None.
        logger: Logger instance.

    Returns:
        bytes — complete PKX file.
    """
    # Apply shiny params to header if provided
    if shiny_params is not None:
        try:
            from ....shared.helpers.pkx import _from_brightness
        except (ImportError, SystemError):
            from shared.helpers.pkx import _from_brightness
        header.shiny_route = (
            shiny_params.route_r, shiny_params.route_g,
            shiny_params.route_b, shiny_params.route_a,
        )
        header.shiny_brightness = (
            _from_brightness(shiny_params.brightness_r),
            _from_brightness(shiny_params.brightness_g),
            _from_brightness(shiny_params.brightness_b),
            _from_brightness(shiny_params.brightness_a),
        )
        logger.info("  Shiny params applied: route=(%d,%d,%d,%d)",
                    shiny_params.route_r, shiny_params.route_g,
                    shiny_params.route_b, shiny_params.route_a)

    if header.is_xd:
        pkx = PKXContainer.build_xd(dat_bytes, header)
    else:
        pkx = PKXContainer.build_colosseum(dat_bytes, header)

    final = pkx.to_bytes()
    logger.info("  Built %s PKX from scratch: %d byte header + %d byte DAT = %d bytes",
                "XD" if header.is_xd else "Colosseum",
                pkx.header_size, len(dat_bytes), len(final))
    return final


def _package_fsys(dat_bytes, filepath, shiny_params, pkx_header, logger):
    """Replace the single model entry inside an existing FSYS archive.

    The pre_process phase already validated that the file exists, has the
    FSYS magic, and contains exactly one model entry. We re-parse here to
    locate that entry, build the appropriate payload (raw DAT or wrapped
    PKX) matching the entry's file type, and re-emit the archive with
    that entry replaced. Other entries' bytes are preserved verbatim.
    """
    with open(filepath, 'rb') as f:
        raw = f.read()

    entries = parse_fsys_summary(raw)
    model_entries = find_model_entries(entries)
    target = model_entries[0]

    if target.model_kind == MODEL_TYPE_PKX:
        payload = _package_pkx(dat_bytes, filepath, shiny_params, pkx_header, logger)
        logger.info("  Built PKX payload for FSYS slot '%s': %d bytes",
                    target.filename, len(payload))
    else:
        payload = dat_bytes
        logger.info("  Using DAT payload for FSYS slot '%s': %d bytes",
                    target.filename, len(payload))

    rebuilt = rebuild_fsys_replacing(raw, target.index, payload)
    logger.info("  FSYS rebuilt: %d entries, %d bytes (was %d)",
                len(entries), len(rebuilt), len(raw))
    return rebuilt


def _inject_into_existing(dat_bytes, filepath, shiny_params, logger):
    """Inject DAT bytes into an existing PKX container file.

    Args:
        dat_bytes: New DAT binary to inject.
        filepath: Path to the existing PKX file.
        shiny_params: ShinyParams to write, or None to preserve existing values.
        logger: Logger instance.

    Returns:
        bytes — the complete PKX file with the new DAT payload.
    """
    pkx = PKXContainer.from_file(filepath)
    logger.info("  Injecting into existing PKX: format=%s, header=0x%X",
                "XD" if pkx.is_xd else "Colosseum", pkx.header_size)

    pkx.dat_bytes = dat_bytes

    if shiny_params is not None:
        pkx.shiny_params = shiny_params
        logger.info("  Shiny params written: route=(%d,%d,%d,%d)",
                    shiny_params.route_r, shiny_params.route_g,
                    shiny_params.route_b, shiny_params.route_a)

    final = pkx.to_bytes()
    logger.info("  PKX output: %d byte header + %d byte DAT = %d bytes total",
                pkx.header_size, len(dat_bytes), len(final))
    return final
