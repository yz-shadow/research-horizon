"""Provision the official portable Ollama distribution inside this project."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time
import urllib.error
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
INSTALLER = ROOT / "installers" / "ollama-windows-amd64.zip"
COMPACT_INSTALLER = ROOT / "installers" / "ollama-windows-x64-vulkan.zip"
COMPACT_SHA256 = "c9d06a4dc440a81299b0c87669d71cc268d8f6d2e593b38535df89e7e95e6f3d"
VERSION = "0.40.5"
DOWNLOAD_URL = f"https://github.com/ollama/ollama/releases/download/v{VERSION}/ollama-windows-amd64.zip"
SHA256 = "5134ce7e3bc8e94d0494721c799ec293b429450d0c52461b0ee3647dd3bb4bb7"
MODEL = "qwen2.5:7b"
API = "http://127.0.0.1:11434"


def api_json(path: str, timeout: float = 3) -> dict:
    with urllib.request.urlopen(API + path, timeout=timeout) as response:
        return json.load(response)


def model_names() -> set[str]:
    return {item["name"] for item in api_json("/api/tags").get("models", [])}


def service_running() -> bool:
    try:
        api_json("/api/version", timeout=1)
        return True
    except (OSError, ValueError):
        return False


def verify_archive(path: Path = INSTALLER, expected: str = SHA256) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("Ollama archive checksum mismatch. Download a fresh official archive.")


def download_runtime() -> None:
    INSTALLER.parent.mkdir(parents=True, exist_ok=True)
    if INSTALLER.exists():
        print("Checking bundled Ollama archive...", flush=True)
        verify_archive()
        return
    temporary = INSTALLER.with_suffix(".zip.part")
    print(f"Downloading official Ollama {VERSION} runtime (~1.47 GB)...", flush=True)
    with urllib.request.urlopen(DOWNLOAD_URL, timeout=60) as response, temporary.open("wb") as stream:
        total = int(response.headers.get("Content-Length", 0))
        done = 0
        last = -1
        while chunk := response.read(1024 * 1024):
            stream.write(chunk)
            done += len(chunk)
            percent = int(100 * done / total) if total else 0
            if percent // 5 != last:
                print(f"Runtime download: {percent}%", flush=True)
                last = percent // 5
    temporary.replace(INSTALLER)
    verify_archive()


def install_runtime() -> Path:
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("The bundled runtime targets Windows x64. Install Ollama for your OS separately.")
    executable = RUNTIME / "ollama" / "ollama.exe"
    stamp = RUNTIME / "ollama" / ".installed-version"
    if executable.exists() and stamp.exists() and stamp.read_text().strip() == VERSION:
        return executable
    if COMPACT_INSTALLER.exists():
        verify_archive(COMPACT_INSTALLER, COMPACT_SHA256)
        archive_path = COMPACT_INSTALLER
    else:
        download_runtime()
        archive_path = INSTALLER
    target = RUNTIME / "ollama"
    target.mkdir(parents=True, exist_ok=True)
    print("Extracting portable Ollama runtime...", flush=True)
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            resolved = (target / member.filename).resolve()
            if not resolved.is_relative_to(target.resolve()):
                raise ValueError("Invalid path in Ollama archive.")
        archive.extractall(target)
    if not executable.exists():
        raise RuntimeError("The archive did not contain ollama.exe at the expected location.")
    stamp.write_text(VERSION, encoding="utf-8")
    return executable


def start_service(install: bool = False) -> None:
    if service_running():
        return
    executable = install_runtime() if install else RUNTIME / "ollama" / "ollama.exe"
    if not executable.exists():
        raise RuntimeError("Run setup_local.py once to install the bundled Ollama runtime and model.")
    RUNTIME.mkdir(exist_ok=True)
    env = os.environ.copy()
    # Scope Ollama's identity files to this portable project, not the real profile.
    profile = RUNTIME / "profile"
    profile.mkdir(exist_ok=True)
    env["USERPROFILE"] = str(profile)
    env["OLLAMA_HOST"] = "127.0.0.1:11434"
    env["OLLAMA_MODELS"] = str(RUNTIME / "models")
    env["OLLAMA_CONTEXT_LENGTH"] = "8192"
    with (RUNTIME / "ollama-server.log").open("ab") as log:
        subprocess.Popen(
            [str(executable), "serve"],
            cwd=executable.parent,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    for _ in range(60):
        if service_running():
            return
        time.sleep(0.5)
    raise RuntimeError(f"Ollama did not start. See {RUNTIME / 'ollama-server.log'}")


def pull_model(model: str = MODEL) -> None:
    if model in model_names():
        print(f"Model already available: {model}", flush=True)
        return
    print(f"Downloading {model}. Keep this window open...", flush=True)
    request = urllib.request.Request(
        API + "/api/pull",
        data=json.dumps({"model": model, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    previous = None
    with urllib.request.urlopen(request, timeout=600) as response:
        for line in response:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("error"):
                raise RuntimeError(event["error"])
            total = event.get("total", 0)
            percent = int(100 * event.get("completed", 0) / total) if total else None
            marker = (event.get("status"), percent // 5 if percent is not None else None)
            if marker != previous:
                print(f"{event.get('status', '')}" + (f" {percent}%" if percent is not None else ""), flush=True)
                previous = marker
    if model not in model_names():
        raise RuntimeError("The model download finished without a usable model. Re-run setup_local.py.")
