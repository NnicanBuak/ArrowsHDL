"""Package resources; editable checkouts and wheels share the same runtime."""
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
REPOSITORY = PACKAGE.parents[1]
SPRITES = PACKAGE / 'data/sprites'
GRAPH_COMPILER = PACKAGE / 'runtime/compile-graph.mjs'
TEMPLATES = PACKAGE / 'data/templates'
