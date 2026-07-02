# RoleRadar

RoleRadar is a Singapore-focused job market intelligence tool.

The current implementation is Phase 0 of the project plan in
`plans/MAIN_PLAN.md`: package scaffolding, configuration, CLI entrypoint, and
smoke tests.

## Development

Use the project virtual environment:

```bash
~/venvs/roleradar/bin/python -m pip install -r requirements.txt
~/venvs/roleradar/bin/python -m pytest tests/
~/venvs/roleradar/bin/python -m roleradar.app.cli --help
```

