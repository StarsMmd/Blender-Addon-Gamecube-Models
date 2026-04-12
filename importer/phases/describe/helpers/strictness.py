"""Strict-mirror mode: decide whether to raise on leniency sites.

The importer normally heals malformed input (rescuing near-zero-scale bones,
fabricating missing vertex colors, etc.) so data that crashes or renders
wrong in-game still loads cleanly in Blender. Strict mode disables that
healing for fault classes the game engine cannot tolerate, so re-exported
bugs become reproducible here.
"""


class StrictMirrorError(RuntimeError):
    """Raised in strict mode when the importer encounters input that the game would crash or render-garbage on."""


def report(logger, options, category, msg, *args, fatal=False):
    """Log a leniency and optionally raise if strict_mirror is enabled."""
    logger.leniency(category, msg, *args)
    if fatal and options and options.get("strict_mirror"):
        formatted = msg % args if args else msg
        raise StrictMirrorError("%s: %s" % (category, formatted))
