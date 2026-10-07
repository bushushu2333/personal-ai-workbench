# Contributing

Small, focused pull requests are welcome. Describe the behavior changed and run
`python -m pytest -q` and `python scripts/privacy_check.py` before publishing.

Keep fixtures synthetic. Never include local configuration, real tasks, imported
Skills, machine inventories, credentials, logs, exported HTML, backups, personal
images or screenshots with actual data. The `examples` directory is public.

Adapters must retain source attribution and truthful unavailable/stale states.
Existing task and Skill sources remain read-only. New integrations should be
explicit opt-ins, with a fixed target allowlist and a documented data flow.

The original UI uses rounded controls and a quiet, warm palette. Avoid decorative
colored side stripes on cards or buttons.
