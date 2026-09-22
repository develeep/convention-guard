"""Run Hypothesis properties without pytest.

The suites in this repository are plain scripts judged by their exit code,
and that does not change for property tests: a `@given` function is just a
function, and calling it runs the examples.

Hypothesis is a development dependency (requirements-dev.txt). It is not
optional: a missing install fails the suite rather than skipping it, so a
property that never ran cannot look like a property that passed (CQ3=A).
Settings are left at their defaults -- the generators stay small enough that
the default deadline is not a factor (CQ2=B).
"""

import traceback

import hypothesis  # noqa: F401  -- fail loudly when it is missing


def run(properties, check):
    """Call each `@given` function; report one line per property."""
    for prop in properties:
        name = prop.__name__.replace('prop_', '').replace('_', ' ')
        try:
            prop()
        except Exception:                       # noqa: BLE001 -- report, do not stop
            check(name, False, _one_line(traceback.format_exc()))
        else:
            check(name, True)


def _one_line(text):
    """The falsifying example and the error, without the frames in between."""
    keep = [line for line in text.strip().split('\n')
            if line.startswith('Falsifying example') or line.startswith('E ')
            or not line.startswith(('  ', 'Traceback'))]
    return ' | '.join(keep[-3:])[:400]
