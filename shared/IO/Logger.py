import os
import sys
import tempfile
import time


class NullLogger:
    """A no-op logger that silently discards all messages.

    Used as the default logger so callers never need to guard against None.
    """
    verbose = False
    warning_count = 0
    error_count = 0
    log_path = None
    log_dir = os.path.join(tempfile.gettempdir(), "blender_dat_import", "unknown")

    def error(self, msg, *args): pass
    def warning(self, msg, *args): pass
    def info(self, msg, *args): pass
    def debug(self, msg, *args): pass
    def close(self): pass


class Logger:
    """Logging for the import/export pipeline.

    Levels:
        ERROR   - Always printed. Failures that affect correctness.
        WARNING - Always printed. Suspicious but non-fatal conditions.
        INFO    - Printed when verbose=True. High-level progress (one line per major step).
        DEBUG   - Printed when verbose=True. Low-level detail (field reads, flag values, etc).

    All messages (regardless of verbose) are written to a log file in the
    system temp directory (tempfile.gettempdir()). The file path is stored
    in self.log_path.

    Usage:
        logger = Logger(verbose=True)
        logger.info("Building model")
        logger.debug("reading field: %s at: 0x%X", field_name, offset)
        logger.warning("GX_DRAW_LINES not supported, skipped")
        logger.error("Failed to decode image format %d", fmt)
    """

    def __init__(self, verbose=False, model_name="unknown"):
        self.verbose = verbose
        self.model_name = model_name
        # Counts for summary
        self.warning_count = 0
        self.error_count = 0

        # Open log file in temp directory, organized by model name
        self.log_dir = os.path.join(tempfile.gettempdir(), "blender_dat_import", model_name)
        os.makedirs(self.log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(self.log_dir, "import_%s.log" % timestamp)
        self._log_file = open(self.log_path, "w")

    def close(self):
        if self._log_file and not self._log_file.closed:
            self._log_file.flush()
            self._log_file.close()

    def error(self, msg, *args):
        self.error_count += 1
        self._print("ERROR", msg, args, file=sys.stderr)

    def warning(self, msg, *args):
        self.warning_count += 1
        self._print("WARNING", msg, args)

    def info(self, msg, *args):
        if self.verbose:
            self._print("INFO", msg, args)
        else:
            self._write("INFO", msg, args)

    def debug(self, msg, *args):
        # Debug always goes to file only — too much output for console
        self._write("DEBUG", msg, args)

    def _print(self, level, msg, args, file=None):
        if args:
            msg = msg % args
        line = "[%s] %s" % (level, msg)
        print(line, file=file)
        self._write_line(line)

    def _write(self, level, msg, args):
        if args:
            msg = msg % args
        self._write_line("[%s] %s" % (level, msg))

    def _write_line(self, line):
        if self._log_file and not self._log_file.closed:
            self._log_file.write(line + "\n")
