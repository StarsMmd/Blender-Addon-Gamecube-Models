"""Phase 4: Convert node trees into an Intermediate Representation scene (pure dataclasses, no bpy)."""
from shared.IR import IRScene


def describe_scene(sections, options):
    """Converts parsed node tree sections into an IRScene.

    Args:
        sections: list of SectionInfo from DATParser.parseSections()
        options: dict of importer options

    Returns:
        IRScene with models, lights, cameras, fogs populated.
    """
    # TODO: Implement as features are ported from legacy build() methods
    return IRScene()
