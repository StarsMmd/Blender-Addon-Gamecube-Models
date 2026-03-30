"""Phase 4 (Export): Package DAT bytes into the final output format.

For .dat output, the DAT bytes are written directly.
For .pkx output, the existing PKX file is read via PKXContainer, the DAT
payload is replaced, and shiny parameters are written back if provided.
"""
try:
    from .....shared.helpers.pkx import PKXContainer
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.pkx import PKXContainer
    from shared.helpers.logger import StubLogger


def package_output(dat_bytes, filepath, options=None, logger=StubLogger(),
                   shiny_params=None):
    """Package DAT bytes into the final output format.

    Args:
        dat_bytes: Raw DAT binary from the serialize phase.
        filepath: Target output file path (extension determines format).
        options: dict of exporter options.
        logger: Logger instance.
        shiny_params: ShinyParams from the describe phase, or None.
                      Written into the PKX header when outputting .pkx files.

    Returns:
        bytes — the final output ready to write to disk.
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 4: Package ===")

    ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''

    if ext == 'pkx':
        final_bytes = _package_pkx(dat_bytes, filepath, shiny_params, logger)
    else:
        final_bytes = dat_bytes

    logger.info("=== Export Phase 4 complete: %d bytes ===", len(final_bytes))
    return final_bytes


def _package_pkx(dat_bytes, filepath, shiny_params, logger):
    """Inject DAT bytes into an existing PKX container.

    Args:
        dat_bytes: New DAT binary to inject.
        filepath: Path to the existing PKX file.
        shiny_params: ShinyParams to write, or None to preserve existing values.
        logger: Logger instance.

    Returns:
        bytes — the complete PKX file with the new DAT payload.
    """
    pkx = PKXContainer.from_file(filepath)
    logger.info("  PKX format: %s, header size: 0x%X",
                "XD" if pkx.is_xd else "Colosseum", pkx.header_size)

    pkx.dat_bytes = dat_bytes

    if shiny_params is not None:
        pkx.shiny_params = shiny_params
        logger.info("  Shiny params written: route=(%d,%d,%d,%d) brightness=(%.2f,%.2f,%.2f,%.2f)",
                    shiny_params.route_r, shiny_params.route_g,
                    shiny_params.route_b, shiny_params.route_a,
                    shiny_params.brightness_r, shiny_params.brightness_g,
                    shiny_params.brightness_b, shiny_params.brightness_a)

    final = pkx.to_bytes()
    logger.info("  PKX output: %d byte header + %d byte DAT = %d bytes total",
                pkx.header_size, len(dat_bytes), len(final))
    return final
