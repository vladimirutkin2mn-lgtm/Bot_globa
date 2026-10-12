# Rollout note

This branch changes only non-group content quality. Group runtime and group scenario files are intentionally untouched.

Daily AI editorial is fail-open to one deterministic shared fallback per date. Personal prompt upgrades are versioned, so old stored readings remain resolvable. Low-confidence routing adds one user clarification rather than a new model call.
