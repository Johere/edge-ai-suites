"""fridge evaluate_rules override.

The fridge use case is intentionally alert-free: its VLM prompt produces
narrative-style summaries used by the report generator, and no motion clip
should ever open an `alerts` row on its own.

The built-in `defaultRuleEvaluator` would fire whenever a summary happened to
contain `SEVERITY: warn` or `SEVERITY: critical`; this stub short-circuits
that path so operators can rely on "fridge never alerts" as an invariant.
"""

import json
import sys


def main() -> None:
    # RuleContext is ignored — fridge never fires.
    _ = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps({"should_alert": False}))


if __name__ == "__main__":
    main()
