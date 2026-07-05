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
MAX_PAGES="${ROLERADAR_MAX_PAGES:-1}"
DEFAULT_LOCATION="${ROLERADAR_LOCATION:-Singapore}"

cd "$ROOT_DIR"

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
  exit 1
fi

echo "[$(date -Is)] scheduled RoleRadar ingestion completed successfully"
