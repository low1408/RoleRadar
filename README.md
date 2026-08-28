# RoleRadar

RoleRadar is a Singapore-focused job market intelligence tool.

The current implementation is Phase 0 of the project plan in
`plans/MAIN_PLAN.md` plus the Phase 1-3 storage, taxonomy, and first Lever
ingestion path.

## Prerequisites

- Python 3.11 or newer.
- The project virtual environment at `~/venvs/roleradar`.
- Node.js and npm for building the React frontend.
- Optional API credentials if you want to ingest from credentialed sources such
  as Adzuna or SSG-WSG.

The project defaults to a local SQLite database at
`data/roleradar.sqlite3`. Runtime configuration is loaded from environment
variables and from a local `.env` file.

## First-time setup

Run all commands from the repository root:

```bash
cd /home/harry/Documents/Github-Projects/personal-projects/RoleRadar
```

Install the Python dependencies into the project virtual environment:

```bash
~/venvs/roleradar/bin/python -m pip install -r requirements.txt
```

Install frontend dependencies:

```bash
npm --prefix frontend install
```

Create a local environment file if you need to override defaults or add API
credentials:

```bash
cp .env.example .env
```

The defaults are enough for a local SQLite-only run. Edit `.env` only when you
need to change the database URL, logging level, timeouts, or source credentials.

## Start the full local app

The simplest startup path is the wrapper script:

```bash
bash run-roleradar.sh
```

The script performs these steps:

1. Uses `~/venvs/roleradar/bin/python` by default.
2. Installs frontend packages if `frontend/node_modules` is missing.
3. Builds the Vite frontend into `roleradar/app/static`.
4. Initializes the SQLite database schema.
5. Starts the FastAPI server.

Open the app at:

```text
http://127.0.0.1:8899
```

Useful script overrides:

```bash
ROLERADAR_PORT=8765 bash run-roleradar.sh
ROLERADAR_HOST=0.0.0.0 bash run-roleradar.sh
ROLERADAR_PYTHON=/path/to/python bash run-roleradar.sh
ROLERADAR_SKIP_FRONTEND_INSTALL=1 bash run-roleradar.sh
ROLERADAR_SKIP_FRONTEND_BUILD=1 bash run-roleradar.sh
```

Use the skip flags only when dependencies are already installed and the frontend
assets are already built.

## Manual startup

If you want to run each step yourself, use this sequence.

Build the frontend:

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

Initialize the database:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli init-db
```

Start the backend and static frontend server:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli serve --host 127.0.0.1 --port 8899
```

The backend serves API routes under `/api/v1` and serves the built frontend
from `roleradar/app/static`.

You can verify the server with:

```bash
curl http://127.0.0.1:8899/api/v1/health
```

## Loading local data

An empty database starts successfully, but most screens will have little or no
data until you seed taxonomy data and ingest job listings.

Seed the skills taxonomy from the bundled CSV:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli seed-taxonomy --file data/skills_framework.csv
```

Ingest public Careers.gov.sg postings:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli ingest --source careers_gov
```

Classify skills for ingested full-text postings:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli classify-skills
```

Check a terminal report:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli report skills --limit 10
```

For board-based ingestion sources such as Lever or Greenhouse, use
`data/target_companies.example.csv` as the starting format for the targets CSV:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli ingest --source lever --targets data/target_companies.example.csv
```

For query-based sources, include the source-specific required options. Examples:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli ingest --source jobstreet --query "data engineer" --location Singapore --max-pages 1
~/venvs/roleradar/bin/python -m roleradar.app.cli ingest --source adzuna --query "data engineer" --location Singapore --country sg --max-pages 1
```

Adzuna requires `ROLERADAR_ADZUNA_APP_ID` and
`ROLERADAR_ADZUNA_APP_KEY` to be configured in `.env` or the environment.

## Development commands

Run tests:

```bash
~/venvs/roleradar/bin/python -m pytest tests/
```

Show CLI help:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli --help
```

Show resolved non-secret configuration:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli config
```

Preview roles that the 30-day closed-role retention policy would delete:

```bash
~/venvs/roleradar/bin/python -m roleradar.app.cli prune-roles --closed-for-days 30 --dry-run
```

Run the Vite development server separately when working on frontend code:

```bash
npm --prefix frontend run dev
```

For normal full-app testing, prefer `bash run-roleradar.sh` because it builds
the frontend into the directory served by FastAPI.

## Troubleshooting

- If the startup script reports that the Python venv is missing, create it or set
  `ROLERADAR_PYTHON=/path/to/python`.
- If the browser shows an old frontend, rebuild with
  `npm --prefix frontend run build` and restart the backend.
- If the app starts but charts are empty, run the taxonomy, ingest, and
  `classify-skills` commands in the data-loading section.
- If ports conflict, start with a different port, for example
  `ROLERADAR_PORT=8765 bash run-roleradar.sh`.
