#!/usr/bin/env python3
"""The bundled YAML parser must read every shipped file exactly like PyYAML.

The hook falls back to lib/miniyaml.py on machines without PyYAML. CI usually
has PyYAML, so without this check a construct miniyaml does not support (a
flow list spanning lines, say) passes every test and silently breaks a rule
for the users who have no pip packages.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import ROOT, check, finish  # noqa: E402
from lib import miniyaml  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

SHIPPED = ['rules/**/*.yaml', 'presets/*.yaml', 'stacks/*.yaml', 'config.yaml',
           'examples/**/*.yaml']


def main():
    if yaml is None:
        print('PyYAML 이 없어 비교를 건너뜁니다')
        return 0
    for pattern in SHIPPED:
        for path in sorted(glob.glob(os.path.join(ROOT, pattern), recursive=True)):
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            try:
                same = yaml.safe_load(text) == miniyaml.load(text)
            except Exception as exc:
                same, rel = False, '%s (%s)' % (rel, exc)
            check('%s parses identically' % rel, same)
    return finish('PyYAML ↔ miniyaml 동등성')


if __name__ == '__main__':
    sys.exit(main())
