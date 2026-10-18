"""Run this file in PyCharm to start Research Horizon."""

from pathlib import Path
import subprocess
import sys

from research_mapper.local_runtime import start_service


if __name__ == "__main__":
    print("Starting Research Horizon...", flush=True)
    try:
        start_service()
        print("Local Ollama service is ready.", flush=True)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Ollama is not ready: {exc}", flush=True)
    app = Path(__file__).resolve().parent / "app.py"
    raise SystemExit(subprocess.call([
        sys.executable, "-m", "streamlit", "run", str(app),
        "--server.address", "127.0.0.1",
    ]))
