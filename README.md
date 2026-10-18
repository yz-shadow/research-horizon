# 研际 · Research Horizon

**连接已有知识，发现下一步可能。**

一个可在 PyCharm 中运行的 Python 项目：从 arXiv 摘要或上传的 PDF 中抽取研究问题、方法和数据集，生成知识图谱与「问题 × 方法」矩阵，并给候选空格展示相邻论文证据。

## 在 PyCharm 中运行

1. 用 PyCharm 打开本目录，创建 Python 3.10+ 虚拟环境。
2. 在 PyCharm 终端运行 `pip install -r requirements.txt`。
3. 打开 `setup_local.py`，点击绿色「运行」。它会校验随包附带的 Ollama Windows x64 便携组件，解压到 `.runtime/ollama`，启动本机服务，从 Qwen 官方 ModelScope 仓库下载 Qwen2.5-7B-Instruct 的 Q4_K_M GGUF 两个分片，逐个校验 SHA256，再导入为本地 `qwen2.5:7b`。模型约 4.7 GB，首次下载需联网；完成后可重复使用。下载中断后重新运行可继续使用已下载的分块。
4. 出现 `Setup complete` 后，打开 `launch.py` 并点击绿色「运行」。以后只需运行该文件，项目会自动启动已安装的 Ollama 服务和网页应用。直接运行 `app.py` 会出现 `missing ScriptRunContext` 提示，无法正常启动界面。

也可以双击 `setup_windows.bat` 完成依赖安装与模型配置，再双击 `run.bat` 启动项目。需要系统已经安装 Python 3.10+。

安装后在项目终端执行 `.\ollama.bat list` 可以查看本地模型；该包装命令使用项目自己的运行目录。打开 [http://127.0.0.1:11434/api/tags](http://127.0.0.1:11434/api/tags) 也可以查看服务与模型状态。

完整分发包包含 `installers/ollama-windows-x64-vulkan.zip`（从官方 Ollama v0.40.5 发行包提取的 CPU 与 Vulkan 便携组件）及许可证。二进制文件保持原样，省略体积较大的两套 CUDA 库，支持 CPU / Vulkan GPU 运行。模型权重与 Python 虚拟环境不打入代码包。文件来源与校验清单见 `installers/README.md` 和 `runtime-manifest.json`。如果随附便携 ZIP 缺失，脚本会从官方 GitHub 下载完整的 Windows x64 发行包（约 1.47 GB）。

这个安装方式不需要注册系统服务或修改全局 PATH；项目通过独立子进程启动 Ollama，并仅监听 `127.0.0.1:11434`。如电脑已有 Ollama 服务，则复用该服务，其模型存储位置由原服务决定。

项目启动的 Ollama 进程使用独立的 `.runtime/profile` 身份目录，密钥不会写入真实的 Windows 用户目录。该设置只作用于项目子进程，不改变 Windows 的全局环境。

默认模型源：[Qwen 官方 ModelScope 仓库](https://modelscope.cn/models/Qwen/Qwen2.5-7B-Instruct-GGUF)。如果希望使用 Ollama 官方注册表，在终端执行 `python setup_local.py --source ollama`。两种方式都在本机运行推理；ModelScope 仅用于下载模型。下载分片的固定 SHA256 记录在 `research_mapper/model_download.py`。Qwen2.5-7B-Instruct 模型采用 Apache 2.0 许可证。

### 安装遇到 Access is denied

如果模型已经下载并校验成功，但模型列表为空、日志出现 `bad manifest` / `Access is denied`，可能是运行环境不能查询模型路径的上层文件夹。请关闭该环境启动的项目 Ollama 进程，再直接在本机 PyCharm 运行 `setup_local.py`，不要一直重新下载模型。脚本会复用已校验的权重和已上传的本地数据。若仍失败，查看 `.runtime/ollama-server.log`，检查当前 Windows 账号对项目及其上层目录的读取权限。安装程序会报告失败，不会把未能识别的模型当作安装成功。

GGUF 分片通过本地 Ollama 的 `/api/blobs` 和 `/api/create` 接口导入，保留原始分片文件名，并显式配置 Qwen 对话模板与停止标记。接口说明：[创建模型](https://docs.ollama.com/api/create)。

没有 Ollama 时，仍可载入 `sample_papers.json` 查看界面和矩阵；对新论文的 AI 抽取需要完成上述安装。arXiv 搜索需要网络；模型下载完成后，上传 PDF 的分析和载入示例可离线使用。扫描版 PDF 没有可提取文字，需要先做 OCR。

## 操作流程

1. 在侧栏选择「arXiv 搜索」「arXiv ID」「上传 PDF」或「示例数据」。
2. 点击「载入论文」，核对论文列表和语料范围。
3. 点击「抽取证据」。每篇论文的结论都必须附有能在输入文本中找到的原文片段；无效片段会被丢弃。
4. 查看知识图谱和矩阵。点击某个格子查看支持论文；打开「候选机会」查看相邻格子的证据链。
5. 在「概念归一」中编辑不同论文的同义标签，再应用映射并查看矩阵变化。
6. 下载 JSON，保存结果供复核和继续分析。

## 方法与边界

- arXiv 搜索和按 ID 载入共用同一进程内的串行请求队列，请求间隔至少 3.1 秒。相同查询成功结果缓存 1 小时（最多 128 条，应用重启后清空）。请只运行一个项目实例；多个进程或其他软件的请求不受此队列管理。
- 对 429 和临时服务错误，每次载入最多请求 3 次，按退避间隔等待，并遵守服务端 `Retry-After`（秒数或 HTTP 日期）。服务端要求等待超过 30 秒时停止自动等待并提示稍后再试；连续 429 后进入共享冷却期，避免换关键词后立即再次请求。失败不会清空已载入论文。限流由 arXiv 控制，这些措施无法保证服务始终可用。
- arXiv 模式分析题名和摘要；PDF 模式读取最多前 20 页可提取的文字，每篇最多分析前 18,000 字。页面会显示来源类型。
- 每个已覆盖的「问题 × 方法」组合至少有一段经原文匹配的证据。数据集是可选信息。
- 一个候选空格需要满足：该问题在别的方法下出现过，且该方法在别的问题下出现过，而二者的直接组合在当前语料中未出现。
- 候选排序仅反映**当前语料中的相邻证据量**，不是新颖性、可行性或全领域研究空白的证明。请到更多数据库和全文中复核。
- 模型负责初次抽取，用户可以通过概念映射修正同义名称。源论文原文和引用始终保留。

## 代码结构

- `app.py`：Streamlit 界面。
- `setup_local.py`：安装项目内的官方 Ollama 运行组件并拉取模型。
- `launch.py`：在 PyCharm 中一键启动 Ollama 与界面。
- `research_mapper/local_runtime.py`：运行包校验、解压、本地服务管理与模型下载。
- `research_mapper/model_download.py`：从 Qwen 官方 ModelScope 仓库下载 GGUF 分片，处理断点续传、SHA256 校验及本地导入。
- `research_mapper/sources.py`：arXiv 检索、ID 查询与 PDF 读取。
- `research_mapper/extract.py`：Ollama 结构化抽取与证据校验。
- `research_mapper/analysis.py`：图谱、矩阵、候选机会和导出数据。
- `sample_papers.json`：仅用于界面演示的合成样例，不代表真实论文。

## 可进一步扩展

接入全文解析与页码定位、领域词表、人工审阅工作流、更完整的文献数据库，以及对候选机会进行跨数据库复检。
