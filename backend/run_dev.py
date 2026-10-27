"""Start the BalanceLoop backend from an IDE: open this file in PyCharm and press Run (▶).

Equivalent to:  uv run uvicorn --app-dir backend app.main:app --reload --port 8000  (from the repo root)
Settings come from backend/.env (see .env.example). Set BL_LLM_PROVIDER=mock there to run offline.
"""
import os
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)  # so .env and the SQLite file resolve relative to backend/
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("BL_PORT", "8000")), reload=True)
