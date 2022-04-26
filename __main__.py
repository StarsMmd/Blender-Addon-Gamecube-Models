import sys
from importer.importer import Importer

# This function is called when the addon is run through the command line.
# To do this first install bpy (`pip install bpy`)
# then run `python <path to repository directory> <path to model>` (i.e. the directory which contains this file and the model to import)
if __name__ == "__main__":
    verbose = False

    if "-v" in sys.argv:
        verbose = True

    for i, arg in enumerate(sys.argv):
        if i > 0:
            if arg[0] == "-":
                continue
            else:
                filepath = arg
                print("importing: " + filepath)
                status = Importer.parseDAT(None, None, filepath, verbose=verbose)
                print(status)