"""Run in PyCharm to install project-local Ollama and download its model."""

from __future__ import annotations

import argparse
import subprocess
import sys

from research_mapper.local_runtime import MODEL, api_json, model_names, pull_model, start_service


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--skip-model", action="store_true")
    parser.add_argument("--source", choices=["modelscope", "ollama"], default="modelscope",
                        help="Default: Qwen official ModelScope GGUF; use ollama for the Ollama registry.")
    args = parser.parse_args()
    try:
        start_service(install=True)
        print(f"Ollama service ready: {api_json('/api/version')}", flush=True)
        if not args.skip_model:
            if args.source == "modelscope" and args.model == MODEL:
                from research_mapper.model_download import install_qwen_from_modelscope
                install_qwen_from_modelscope()
            else:
                pull_model(args.model)
        print(f"Installed models: {', '.join(sorted(model_names()))}", flush=True)
        print("Setup complete. Run launch.py in PyCharm.", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
