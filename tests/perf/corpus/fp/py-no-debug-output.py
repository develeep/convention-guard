"""Report helpers.

print(report) is what this module replaces -- a docstring, not a call.
"""
import logging

log = logging.getLogger(__name__)


def render(report):
    # print(report)  -- the old way
    hint = "print(report) writes to stdout"
    label = f"{report.name}: print() is not called here"
    print(report.total)
    return f"{hint} {label}"
