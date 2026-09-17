"""Rules: file format (schema), layering and presets (loader), applicability (select)."""

from .loader import (LEGACY_DIRNAME, REPO_DIRNAME, SELF_PATHS, RuleSet,  # noqa: F401
                     deep_merge, iter_rule_files, legacy_layout, load, load_presets,
                     local_rules_dir, repo_dir, user_rules_dir)
from .schema import RuleError, normalize  # noqa: F401
from .select import (SEVERITIES, applicable, applies, glob_re, match_any,  # noqa: F401
                     path_ok, severity_rank, stack_ok, superseded)
