"""Rules: file format (schema), layering and presets (loader), applicability (select)."""

from .loader import (REPO_DIRNAME, SELF_PATHS, RuleSet,  # noqa: F401
                     deep_merge, iter_rule_files, load, load_presets,
                     local_rules_dir, repo_dir, user_rules_dir)
from .schema import RuleError, normalize  # noqa: F401
from .select import (SEVERITIES, Reach, applicable, glob_re, match_any,  # noqa: F401
                     severity_rank, stack_ok, superseded)
