# Included Ollama runtime

`ollama-windows-x64-vulkan.zip` is a compact portable distribution assembled from the official Ollama v0.40.5 Windows x64 archive. It includes all files except the `cuda_v12` and `cuda_v13` folders. The included CPU / Vulkan binaries are unmodified. This is a project-packaged selection, not the original full archive or the official GUI installer.

- Source: https://github.com/ollama/ollama/releases/tag/v0.40.5
- Archive: https://github.com/ollama/ollama/releases/download/v0.40.5/ollama-windows-amd64.zip
- Full official archive SHA256 (release metadata): `5134ce7e3bc8e94d0494721c799ec293b429450d0c52461b0ee3647dd3bb4bb7`
- Compact archive and included file SHA256 values: see `runtime-manifest.json`.
- Copyright and license: see `OLLAMA_LICENSE.txt` and notices inside the official runtime archive.

The files were fetched over HTTPS from the official archive using ZIP range extraction, with each entry's size and ZIP CRC checked. The project verifies the compact archive SHA256 before extracting it into `.runtime/ollama`. The full official archive checksum above is provenance metadata, not a claim that the complete 1.47 GB file was downloaded.
Model weights are not inside this code package. `setup_local.py` downloads official Qwen2.5-7B-Instruct Q4_K_M GGUF shards from https://modelscope.cn/models/Qwen/Qwen2.5-7B-Instruct-GGUF, verifies their fixed SHA256 checksums, and imports them as local `qwen2.5:7b`. Use `--source ollama` to pull from the Ollama registry instead. The model is Apache 2.0 licensed. Model weights and identity files stay in `.runtime/` and are excluded from the distribution.

The archive is Windows x64 only. Other operating systems should install Ollama separately and use its standard localhost API.
