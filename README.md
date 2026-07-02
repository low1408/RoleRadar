# RoleRadar

RoleRadar is a Singapore-focused job market intelligence tool.

The current implementation is Phase 0 of the project plan in
`plans/MAIN_PLAN.md` plus the Phase 1-3 storage, taxonomy, and first Lever
ingestion path.

## Development

Use the project virtual environment:

```bash
~/venvs/roleradar/bin/python -m pip install -r requirements.txt
~/venvs/roleradar/bin/python -m pytest tests/
~/venvs/roleradar/bin/python -m roleradar.app.cli --help
```

## Local Workflow

```bash
~/venvs/roleradar/bin/roleradar init-db
~/venvs/roleradar/bin/roleradar seed-taxonomy --file data/skills_framework.csv
~/venvs/roleradar/bin/roleradar ingest --source lever --targets data/target_companies.csv
~/venvs/roleradar/bin/roleradar report skills --limit 10
```

Use `data/target_companies.example.csv` as the starting format for Lever target
companies.
