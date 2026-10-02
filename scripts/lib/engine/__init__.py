"""The structure engine: tree-sitter, installed by convention-guard itself.

    tags.py     which wheels this interpreter can load
    install.py  fetch, verify, unpack, self-test (standard library only)
    loader.py   import the installed engine, or say why it is missing
    lock.json   the pinned wheels and their sha256 (scripts/engine.py lock)
"""
