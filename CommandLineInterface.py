"""Command-line interface for importing DAT models."""
import os
import sys

from importer.importer import Importer
from shared.helpers.logger import Logger


def main():
    """Parse CLI arguments, read file, and run the import pipeline."""
    verbose = "-v" in sys.argv

    for i, arg in enumerate(sys.argv):
        if i == 0 or arg.startswith("-"):
            continue

        filepath = arg
        filename = os.path.basename(filepath)
        model_name = filename.split('.')[0] if filename else "unknown"

        if verbose:
            print("importing: " + filepath)

        with open(filepath, 'rb') as f:
            raw_bytes = f.read()

        logger = Logger(verbose=verbose, model_name=model_name)

        try:
            import bpy
            context = bpy.context
        except ImportError:
            context = None

        options = {
            "ik_hack": True,
            "verbose": verbose,
            "max_frame": 1000000000,
            "section_names": [],
            "filepath": filepath,
        }

        status = Importer.run(context, raw_bytes, filename, options, logger=logger)
        print(status)


if __name__ == "__main__":
    main()
