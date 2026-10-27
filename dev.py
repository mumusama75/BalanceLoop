"""One-click full stack for the demo: starts the Vite frontend (npm run dev) and the FastAPI backend.

Run it from PyCharm (▶ on this file) or:  uv run python dev.py
Stops both when you press Stop / Ctrl-C. Installs frontend packages on first run if node_modules is missing.
"""
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND, FRONTEND = ROOT / "backend", ROOT / "frontend"


def main() -> None:
    npm = shutil.which("npm")
    if npm is None:
        print("npm not found — install Node.js (https://nodejs.org) or start the frontend separately.", file=sys.stderr)
    front = None
    if npm:
        if not (FRONTEND / "node_modules").exists():
            print(">>> npm install (first run)")
            subprocess.run([npm, "install"], cwd=FRONTEND, check=True)
        print(">>> frontend: npm run dev  →  http://localhost:5173", flush=True)
        # own process group so that Stop/Ctrl-C also ends the vite child that npm spawns
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        front = subprocess.Popen([npm, "run", "dev"], cwd=FRONTEND, **group)
    try:
        os.chdir(BACKEND)
        sys.path.insert(0, str(BACKEND))
        import uvicorn  # noqa: E402  (installed into ./.venv by `uv sync`, or by pip install -r requirements.txt)
        print(">>> backend: uvicorn app.main:app  →  http://localhost:8000/docs", flush=True)
        uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
    finally:
        if front and front.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(front.pid)], capture_output=True)
            else:
                os.killpg(os.getpgid(front.pid), signal.SIGTERM)
            try:
                front.wait(timeout=5)
            except subprocess.TimeoutExpired:
                front.kill()


if __name__ == "__main__":
    main()
