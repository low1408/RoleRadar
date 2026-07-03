#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROLERADAR_PYTHON:-$HOME/venvs/roleradar/bin/python}"
HOST="${ROLERADAR_HOST:-127.0.0.1}"
PORT="${ROLERADAR_PORT:-8899}"
SKIP_FRONTEND_INSTALL="${ROLERADAR_SKIP_FRONTEND_INSTALL:-0}"
SKIP_FRONTEND_BUILD="${ROLERADAR_SKIP_FRONTEND_BUILD:-0}"

cd "$ROOT_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python venv not found or not executable: $PYTHON_BIN" >&2
  echo "Set ROLERADAR_PYTHON=/path/to/python if your venv is elsewhere." >&2
  exit 1
fi

if [[ ! -d "frontend" ]]; then
  echo "Missing frontend/ directory. Run this script from a checkout with the frontend files." >&2
  exit 1
fi

if [[ "$SKIP_FRONTEND_INSTALL" != "1" ]]; then
  if [[ ! -d "frontend/node_modules" ]]; then
    echo "Installing frontend dependencies..."
    npm --prefix frontend install
  fi
fi

if [[ "$SKIP_FRONTEND_BUILD" != "1" ]]; then
  echo "Building frontend..."
  npm --prefix frontend run build
fi

echo "Initializing database schema..."
"$PYTHON_BIN" -m roleradar.app.cli init-db

echo "Starting RoleRadar at http://$HOST:$PORT"
exec "$PYTHON_BIN" -m roleradar.app.cli serve --host "$HOST" --port "$PORT"
