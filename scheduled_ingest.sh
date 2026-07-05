#!/usr/bin/env bash
# scheduled_ingest.sh
#
# Cron example, daily at 06:00:
# 0 6 * * * /home/harry/Documents/Github-Projects/personal-projects/RoleRadar/scheduled_ingest.sh >> /home/harry/Documents/Github-Projects/personal-projects/RoleRadar/scheduled_ingest.log 2>&1
#
# Cron only runs while the computer is on. If missed runs should execute after
# boot, prefer a systemd user timer with Persistent=true that calls this script.
#
# Tune with:
#   ROLERADAR_PYTHON=/path/to/python
#   ROLERADAR_RESULTS_PER_PAGE=50
#   ROLERADAR_MAX_PAGES=2
#   ROLERADAR_LOCATION=Singapore

set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROLERADAR_PYTHON:-$HOME/venvs/roleradar/bin/python}"
RESULTS_PER_PAGE="${ROLERADAR_RESULTS_PER_PAGE:-20}"
DEFAULT_LOCATION="${ROLERADAR_LOCATION:-Singapore}"

cd "$ROOT_DIR"

# 1. Prevent concurrent runs using flock
mkdir -p data
exec 9>"data/ingest.lock"
if ! flock -n 9; then
  echo "[$(date -Is)] RoleRadar ingestion is already running. Exiting." >&2
  exit 1
fi

# 2. Dual-Mode: Sunday deep sync (5 pages), weekdays shallow sync (1 page)
DOW=$(date +%u)
if [[ "${ROLERADAR_MAX_PAGES:-}" -gt 0 ]]; then
  MAX_PAGES="$ROLERADAR_MAX_PAGES"
elif [[ "$DOW" -eq 7 ]]; then
  echo "[$(date -Is)] Sunday deep sync triggered (fetching up to 5 pages)"
  MAX_PAGES=5
else
  MAX_PAGES=1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python venv not found or not executable: $PYTHON_BIN" >&2
  echo "Set ROLERADAR_PYTHON=/path/to/python if your venv is elsewhere." >&2
  exit 1
fi

declare -a INGEST_TARGETS=(
  "careers_gov|data engineer|data_engineer|"
  "careers_gov|software engineer|software_engineer|"
  "careers_gov|AI engineer|ai_ml_engineer|"
  "careers_gov|data scientist|data_scientist|"
  "careers_gov|data analyst|data_analyst|"
  "careers_gov|cloud engineer|cloud_devops_engineer|"
  "careers_gov|devops engineer|cloud_devops_engineer|"
  "careers_gov|product manager|product_manager|"
  "careers_gov|cybersecurity|cybersecurity|"
  # JobStreet is intentionally disabled until the source is verified.
  # "jobstreet|AI engineer|ai_ml_engineer|$DEFAULT_LOCATION"
  # "jobstreet|data engineer|data_engineer|$DEFAULT_LOCATION"
)

echo "[$(date -Is)] starting scheduled RoleRadar ingestion"
if ! "$PYTHON_BIN" -m roleradar.app.cli init-db; then
  echo "[$(date -Is)] database initialization failed" >&2
  exit 1
fi

failures=0

for target in "${INGEST_TARGETS[@]}"; do
  IFS="|" read -r source query role_family location <<< "$target"

  command=(
    "$PYTHON_BIN"
    -m roleradar.app.cli
    ingest
    --source "$source"
    --query "$query"
    --role-family "$role_family"
    --results-per-page "$RESULTS_PER_PAGE"
    --max-pages "$MAX_PAGES"
  )

  if [[ -n "$location" ]]; then
    command+=(--location "$location")
  fi

  echo "[$(date -Is)] ingesting source=$source query=$query role_family=$role_family"
  if "${command[@]}"; then
    echo "[$(date -Is)] completed source=$source query=$query role_family=$role_family"
  else
    status=$?
    failures=$((failures + 1))
    echo "[$(date -Is)] failed source=$source query=$query role_family=$role_family exit_status=$status" >&2
  fi
done

if [[ "$failures" -gt 0 ]]; then
  echo "[$(date -Is)] scheduled RoleRadar ingestion completed with $failures failure(s)" >&2
  # Send desktop notification on failure if in a desktop session
  if command -v notify-send >/dev/null 2>&1; then
    notify-send "RoleRadar Ingestion Failed" "Scheduled job ingestion encountered $failures failure(s). Check scheduled_ingest.log for details." --icon=dialog-error
  fi
  exit 1
fi

echo "[$(date -Is)] scheduled RoleRadar ingestion completed successfully"
if command -v notify-send >/dev/null 2>&1; then
  notify-send "RoleRadar Ingestion Successful" "Job listings have been loaded and updated." --icon=dialog-information
fi
