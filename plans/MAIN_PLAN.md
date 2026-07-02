# RoleRadar Main Implementation Plan

RoleRadar is a Singapore-focused job market intelligence tool. The MVP should prove one reliable ingestion-to-insight path before expanding to broad source coverage.

This plan favors stable, permission-aware data sources first. Experimental or unofficial collectors must be isolated, disabled by default, and unable to break the primary ingestion and analytics pipeline.

## Guiding Principles

- Build vertical slices before broad scaffolding.
- Preserve source provenance instead of collapsing records too early.
- Prefer official APIs and public job-board APIs over scraping.
- Treat scraping and browser automation as last-resort, source-specific experiments.

- Track posting lifecycle using repeated observations, not assumed posting dates.
- Keep LLM usage out of the ingestion path unless there is a measured need.

## Source Policy

### Supported MVP Sources

- **Greenhouse**: primary source candidate. Public job board API supports listing jobs and retrieving content without auth for GET endpoints.
- **Lever**: primary source candidate. Public postings API exposes full description fields for published postings.
- **Local SSG Skills Framework seed files**: taxonomy seed source. Load from local CSV or Excel snapshots first.

### Secondary Sources

- **Adzuna**: official API, useful for coverage and salary signals, but description text is often only a snippet. Do not rely on it as the primary skill extraction source.
- **SSG-WSG API**: optional future sync path when credentials and endpoint access are available. The MVP should not depend on live API availability.

### Experimental Sources

- **Careers@Gov**: experimental public-web collector, disabled by default. Must follow robots/terms constraints, throttle requests, store provenance, and fail closed.
- **JobStreet**: blocked pending written permission or documented API access. Do not implement scraping, browser automation, GraphQL calls, or anti-bot workarounds as part of MVP.

## Phase 0: Project Foundation

Goal: create a minimal Python package that can be installed, configured, tested, and invoked from the CLI.

Deliverables:

- `pyproject.toml` with package metadata, console script, and tool configuration.
- `requirements.txt` or equivalent dependency list.
- `.env.example` for local configuration.
- `roleradar/` package structure.
- `tests/` directory with smoke tests.
- CLI entrypoint with `roleradar --help`.

Initial dependencies:

- `sqlalchemy`
- `pydantic`
- `pydantic-settings`
- `click`
- `requests`
- `python-dotenv`
- `structlog`
- `pytest`

Verification:

- `~/venvs/roleradar/python -m pytest tests/`
- `~/venvs/roleradar/python -m roleradar.app.cli --help`

Exit criteria:

- Package imports cleanly.
- CLI help renders.
- Test suite runs from a fresh checkout.

## Phase 1: Storage, Provenance, and Lifecycle Schema

Goal: build the database shape needed for trustworthy ingestion and trend tracking.

Core tables:

- `ingestion_runs`
- `source_listings`
- `jobs`
- `companies`
- `skills`
- `skill_aliases`
- `job_skills`
- `posting_observations`

Important lifecycle fields:

- `first_seen_at`
- `last_seen_at`
- `closed_at`
- `observed_at`
- `source_updated_at`
- `raw_payload`

Important source fields:

- `source`
- `source_job_id`
- `canonical_url`
- `source_url`
- `source_company_name`
- `source_title`
- `content_hash`

SQLite configuration:

- Enable WAL mode for file-backed SQLite databases.
- Set `busy_timeout`.
- Use short write transactions.
- Use batched inserts.
- Avoid relying on in-memory SQLite tests for WAL behavior.

Verification:

- Create a file-backed test database.
- Insert one ingestion run.
- Insert source listings and canonical jobs.
- Re-run inserts and verify idempotency.

Exit criteria:

- Duplicate source records are ignored or updated deterministically.
- Source provenance is preserved.
- Posting observations can support future trend calculations.

## Phase 2: Local Taxonomy Seed Loading

Goal: load skills and aliases from local seed files before integrating live taxonomy APIs.

Deliverables:

- `roleradar/sources/seed_loader.py`
- `roleradar/analytics/skill_matcher.py`
- CLI command: `roleradar seed-taxonomy --file <path>`

Seed format:

- `skill_name`
- `category`
- `source_taxonomy`
- `alias`
- `match_type`
- `case_sensitive`

Matching requirements:

- Use curated aliases, not generic word-boundary regex only.
- Support special cases like `C++`, `C#`, `.NET`, `Node.js`, `R`, `Go`, `SQL Server`.
- Store extraction method and confidence on `job_skills`.

Verification:

- Unit tests for ambiguous aliases.
- Confirm `Go` does not match ordinary phrases like `go live`.
- Confirm special-character skills match correctly.

Exit criteria:

- Taxonomy can be loaded repeatedly without creating duplicates.
- Skill extraction is deterministic and test-covered.

## Phase 3: First Reliable Ingestion Path

Goal: ingest full-text job postings from one stable source and produce a useful skill report.

Recommended first source:

- Start with **Lever** or **Greenhouse**, whichever has a clear target-company list available.

Deliverables:

- `data/target_companies.example.csv`
- `roleradar/sources/lever.py` or `roleradar/sources/greenhouse.py`
- `roleradar/ingestion/normalize_jobs.py`
- `roleradar/ingestion/fetch_jobs.py`
- CLI command: `roleradar ingest --source lever --targets data/target_companies.csv`

Target company fields:

- `company_name`
- `source`
- `board_token_or_site`
- `enabled`
- `notes`

Normalization requirements:

- Normalize title, company, location, workplace type, salary, source URL, and description text.
- Store the original raw payload.
- Compute a content hash.
- Record every run in `ingestion_runs`.

Verification:

- Use saved JSON fixtures.
- Run ingestion twice and verify idempotency.
- Confirm descriptions are present and skill extraction runs.

Exit criteria:

- At least one real source can be ingested end to end.
- Re-running ingestion updates observations instead of duplicating jobs.
- A report can list top skills from active postings.

## Phase 4: MVP Analytics and Reporting

Goal: produce useful local reports without pretending to have mature trend data.

Deliverables:

- `roleradar/analytics/skill_trends.py`
- `roleradar/analytics/salary_trends.py`
- CLI command: `roleradar report skills --days 30`
- CLI command: `roleradar report salaries --days 30`

Initial report metrics:

- Top skills by active postings.
- Skills by source.
- Skills by company.
- Skills by role/title keyword.
- Salary range summary where employer-provided salary exists.

Trend caveat:

- Do not label metrics as growth until repeated observations exist across time windows.
- Before enough history exists, report `current snapshot` metrics only.

Verification:

- Fixture-backed report tests.
- Snapshot report output for a small deterministic dataset.

Exit criteria:

- CLI report produces stable, readable output.
- Reports distinguish current snapshot metrics from historical trends.

## Phase 5: Add Second Stable Source

Goal: expand from one stable full-text source to two, then validate cross-source data modeling.

Deliverables:

- Implement the other source: Greenhouse if Lever came first, or Lever if Greenhouse came first.
- Shared source interface for fetching and normalizing listings.
- Cross-source duplicate candidate detection.

Deduplication approach:

- Hard identity: `(source, source_job_id)`.
- Strong identity: canonical source URL.
- Candidate match only: normalized company, normalized title, location, and similar content hash.
- Never delete source listings when merging into canonical jobs.

Verification:

- Fixture with the same job appearing through two sources.
- Confirm both source listings remain linked to one canonical job candidate.

Exit criteria:

- Two stable sources can run independently.
- A failure in one source does not fail the whole ingestion run.
- Cross-source candidates are logged and reviewable.

## Phase 6: Adzuna Integration

Goal: add Adzuna as an official API source for broader market coverage, with clear data-quality boundaries.

Deliverables:

- `roleradar/sources/adzuna.py`
- CLI command: `roleradar ingest --source adzuna --query "data analyst" --location Singapore`

Rules:

- Store Adzuna descriptions as snippets unless full source text is lawfully retrieved from another allowed source.
- Mark text quality as `snippet`.
- Avoid mixing snippet-derived skill counts with full-description-derived counts without labeling them.

Verification:

- Mock API responses.
- Pagination tests.
- Rate-limit handling tests.

Exit criteria:

- Adzuna ingestion works through the same source interface.
- Reports can include or exclude snippet-only sources.

## Phase 7: Careers@Gov Experimental Collector

Goal: evaluate whether Careers@Gov can be collected responsibly and reliably.

Status:

- Disabled by default.
- Not part of MVP success criteria.

Deliverables:

- `roleradar/sources/careers_gov.py`
- Feature flag: `ROLERADAR_ENABLE_EXPERIMENTAL_SOURCES=false`
- Source-specific throttle and timeout settings.
- Clear logging for skipped, blocked, or changed pages.


Exit criteria:

- Collector can be enabled explicitly for local experimentation.
- Any error is isolated to this source.


## Phase 8: SSG-WSG Live Sync

Goal: supplement local taxonomy seed data with live official API data when credentials and stable endpoint access are available.

Deliverables:

- `roleradar/sources/ssg_wsg.py`
- CLI command: `roleradar sync-taxonomy --source ssg-wsg`
- Credential configuration through environment variables.

Rules:

- Local seed loading remains the fallback.
- API sync should upsert taxonomy records, not replace local curated aliases blindly.
- Track taxonomy version/source timestamps where available.

Verification:

- Mock API tests.
- Contract fixtures for expected API responses.

Exit criteria:

- Live sync can update taxonomy without breaking local aliases.
- Missing credentials produce a clear skip message.

## Phase 9: JobStreet Permission Gate

Goal: explicitly document what must happen before JobStreet data can be integrated.

Status:

- Blocked pending written permission or documented API access.

Do not implement:

- HTML scraping.
- Browser automation to collect postings.
- Calls to private GraphQL or internal API endpoints.
- Session-header spoofing.
- Anti-bot or Cloudflare workarounds.

Allowed future paths:

- SEEK/JobStreet partner API access with written approval.
- Licensed data export.
- Employer-owned postings supplied directly by companies.
- Public metadata only where terms allow it.

Exit criteria:

- Written permission, API documentation, and permitted use cases are recorded in project docs.
- Implementation scope is reviewed before coding begins.

## Phase 10: Operational Hardening

Goal: make repeated local ingestion predictable and diagnosable.

Deliverables:

- Source run summaries.
- Retry policy with backoff for official APIs.
- Per-source timeouts.
- Structured logs.
- Database maintenance command.
- Manual checkpoint command for SQLite WAL if needed.

CLI examples:

```bash
roleradar init-db
roleradar seed-taxonomy --file data/skills_framework.csv
roleradar ingest --source lever --targets data/target_companies.csv
roleradar report skills --days 30
roleradar db stats
```

Verification:

- Run a full local pipeline from an empty database.
- Confirm failures are source-scoped.
- Confirm database stats match expected fixture counts.

Exit criteria:

- A new user can run the MVP locally from documented commands.
- Logs explain what was fetched, skipped, inserted, updated, and failed.

## MVP Definition

The MVP is complete when:

- Local taxonomy seed loading works.
- One full-text source, Lever or Greenhouse, ingests successfully.
- Job postings retain source provenance and lifecycle observations.
- Skill extraction is deterministic and tested.
- The CLI can produce a top-skills current snapshot report.
- Tests pass using `~/venvs/roleradar/python`.

Non-MVP:

- JobStreet integration.
- Live SSG-WSG API sync.
- LLM summaries.
- Mature growth/trend claims.
- Browser automation.
- Web UI.

## Immediate Next Checklist

- Create Python package scaffold.
- Define SQLAlchemy models for ingestion runs, source listings, jobs, companies, skills, aliases, and observations.
- Add `init-db` CLI command.
- Add local taxonomy seed loader.
- Pick first source: Lever or Greenhouse.
- Add target-company seed file format.
- Implement first source ingestion with fixtures.
- Add current snapshot skills report.
