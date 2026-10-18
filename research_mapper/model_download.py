"""Download Qwen's official GGUF shards from ModelScope and import locally."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import http.client
import json
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error

from research_mapper.local_runtime import API, MODEL, ROOT, RUNTIME, model_names


BASE = "https://modelscope.cn/models/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/master/"
SHARDS = [
    ("qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf", 3993201344,
     "dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db"),
    ("qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf", 689872288,
     "539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a"),
]

# ChatML format for Qwen's system/user/assistant messages. The project does
# not use tool calls. An explicit template is needed when importing raw GGUF.
CHAT_TEMPLATE = """{{ if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}{{ range .Messages }}{{ if ne .Role "system" }}<|im_start|>{{ .Role }}
{{ .Content }}<|im_end|>
{{ end }}{{ end }}<|im_start|>assistant
"""


def resolve_download_url(name: str) -> str:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(urllib.request.Request(BASE + name, method="HEAD"), timeout=25):
            return BASE + name
    except urllib.error.HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            location = exc.headers.get("Location", "")
            if location.startswith("https://"):
                return location
        raise


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download_shard(name: str, size: int, expected: str) -> Path:
    directory = RUNTIME / "downloads" / "qwen2.5-7b"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if target.exists() and target.stat().st_size == size and sha256(target) == expected:
        print(f"Verified cached shard: {name}", flush=True)
        return target
    chunks = directory / (name + ".chunks")
    chunks.mkdir(exist_ok=True)
    block = 8 * 1024 * 1024
    count = (size + block - 1) // block
    direct_url = resolve_download_url(name)
    url_lock = threading.Lock()

    def fetch(index: int) -> int:
        nonlocal direct_url
        start = index * block
        end = min(size, start + block) - 1
        path = chunks / str(index)
        length = end - start + 1
        if path.exists() and path.stat().st_size == length:
            return length
        partial = chunks / f"{index}.partial"
        for attempt in range(10):
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                if offset > length:
                    partial.unlink()
                    offset = 0
                if offset == length:
                    partial.replace(path)
                    return length
                request_start = start + offset
                request_url = direct_url
                request = urllib.request.Request(request_url, headers={"Range": f"bytes={request_start}-{end}"})
                with urllib.request.urlopen(request, timeout=25) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {request_start}-{end}/{size}":
                        raise ValueError("Unexpected model download range response")
                    with partial.open("ab") as stream:
                        while data := response.read(64 * 1024):
                            stream.write(data)
                if partial.stat().st_size != length:
                    raise ValueError("Incomplete model download range")
                partial.replace(path)
                return length
            except (OSError, ValueError) as exc:
                if attempt == 9:
                    raise
                if isinstance(exc, urllib.error.HTTPError) and exc.code in {401, 403, 410}:
                    with url_lock:
                        if direct_url == request_url:
                            direct_url = resolve_download_url(name)
                print(f"Retrying block {index}: {exc}", flush=True)
                time.sleep(attempt + 1)

    print(f"Downloading official Qwen shard: {name}", flush=True)
    done, last = 0, 0.0
    with ThreadPoolExecutor(max_workers=16) as pool:
        tasks = [pool.submit(fetch, index) for index in range(count)]
        for task in as_completed(tasks):
            done += task.result()
            if time.time() - last >= 5:
                print(f"{done / size:.1%}, {done // 1048576}/{size // 1048576} MiB", flush=True)
                last = time.time()
    partial = target.with_suffix(".gguf.part")
    with partial.open("wb") as stream:
        for index in range(count):
            stream.write((chunks / str(index)).read_bytes())
    print("Verifying shard SHA256...", flush=True)
    if sha256(partial) != expected:
        # Do not reuse untrusted cached parts after an integrity failure.
        for index in range(count):
            (chunks / str(index)).unlink(missing_ok=True)
            (chunks / f"{index}.partial").unlink(missing_ok=True)
        raise ValueError(f"Model SHA256 mismatch for {name}. Re-run setup_local.py.")
    partial.replace(target)
    for index in range(count):
        (chunks / str(index)).unlink(missing_ok=True)
    chunks.rmdir()
    return target


def install_qwen_from_modelscope() -> None:
    if MODEL in model_names():
        print(f"Model already available: {MODEL}", flush=True)
        return
    paths = [download_shard(*row) for row in SHARDS]
    # Upload through the API so the server owns its blob storage, including
    # when another local Ollama installation is already listening.
    for path, (_, size, digest) in zip(paths, SHARDS):
        connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=600)
        try:
            endpoint = f"/api/blobs/sha256:{digest}"
            connection.request("HEAD", endpoint)
            response = connection.getresponse()
            response.read()
            if response.status == 200:
                continue
            if response.status != 404:
                raise RuntimeError(f"Cannot check model blob: HTTP {response.status}")
            print(f"Importing shard: {path.name}", flush=True)
            connection.putrequest("POST", endpoint)
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Content-Length", str(size))
            connection.endheaders()
            with path.open("rb") as stream:
                while chunk := stream.read(8 * 1024 * 1024):
                    connection.send(chunk)
            response = connection.getresponse()
            detail = response.read().decode("utf-8", errors="replace")
            if response.status != 201:
                raise RuntimeError(f"Model blob import failed: HTTP {response.status}: {detail}")
        finally:
            connection.close()
    print("Importing verified GGUF shards into Ollama...", flush=True)
    payload = {
        "model": MODEL,
        "files": {name: f"sha256:{digest}" for name, _, digest in SHARDS},
        "template": CHAT_TEMPLATE,
        "parameters": {"num_ctx": 8192, "stop": ["<|im_start|>", "<|im_end|>"]},
        "license": (ROOT / "installers" / "QWEN_LICENSE.txt").read_text(encoding="utf-8"),
        "stream": False,
    }
    request = urllib.request.Request(
        API + "/api/create", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.load(response)
    if result.get("status") != "success":
        raise RuntimeError(f"Model import failed: {result}")
    if MODEL not in model_names():
        request = urllib.request.Request(
            API + "/api/show", data=json.dumps({"model": MODEL}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama could not read the imported model: {detail}. "
                "If this says Access is denied, run setup_local.py directly in "
                "your local PyCharm and check .runtime/ollama-server.log. "
                "Verified model downloads are cached and will be reused."
            ) from exc
        raise RuntimeError("Model import completed but /api/tags did not list the model. Check the Ollama server log.")
