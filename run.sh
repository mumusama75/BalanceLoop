#!/usr/bin/env bash
# One-command helpers for the demo.
#   ./run.sh setup            uv sync (creates ./.venv) and npm install
#   ./run.sh backend          start FastAPI on :8000 (uses backend/.env; BL_LLM_PROVIDER=mock ./run.sh backend for offline)
#   ./run.sh frontend         start the Vite dev server on :5173
#   ./run.sh all              both servers (python dev.py)
#   ./run.sh test             run the backend test-suite (offline)
#   ./run.sh reset            wipe and re-seed the demo database of a running backend
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
case "${1:-}" in
  setup)    cd "$ROOT" && uv sync && cd "$ROOT/frontend" && npm install ;;
  backend)  cd "$ROOT" && uv run uvicorn --app-dir backend app.main:app --reload --port 8000 ;;
  frontend) cd "$ROOT/frontend" && npm run dev ;;
  all)      cd "$ROOT" && uv run python dev.py ;;
  test)     cd "$ROOT" && uv run pytest -q ;;
  reset)    curl -s -X POST http://localhost:8000/api/admin/reset-demo && echo ;;
  *) sed -n '2,9p' "$0" ;;
esac
