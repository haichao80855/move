# Move · 视频翻译工作台

在 Apple Silicon Mac 本机运行的中文视频翻译工具。用浏览器完成 **导入视频 → 识别字幕 → 校对 → 翻译 → 试听配音 → 导出**。媒体文件保存在本机，翻译和配音在你主动启动任务时调用云端服务。

首版面向 M1 Pro / 16 GB 的英文视频转中文场景：Parakeet MLX 识别、Whisper MLX 局部补识别、DeepSeek / Qwen 翻译、MiniMax 系统音色配音、FFmpeg 合成。

## Mac 安装与启动

需要 Apple Silicon Mac（推荐 macOS 14 或更新版本）、Python 3.11–3.13、Node.js 22.12+ 或 24，以及带 libx264 / libass 的 FFmpeg。推荐先安装 [Homebrew](https://brew.sh)，再运行：

```bash
brew install uv node ffmpeg
git clone https://github.com/haichao80855/move.git
cd move
./scripts/install.sh
./scripts/install-asr.sh
./scripts/start.sh
```

`uv` 会使用符合版本要求的 Python（必要时下载）。启动后打开 `http://127.0.0.1:8000`。也可在 Finder 双击 `start.command`。关闭终端或按 Ctrl+C 停止服务；已完成的项目和片段保留。

识别模型在第一次使用时下载至 Hugging Face 缓存；安装脚本不会提前下载大型权重。首次识别需要访问 Hugging Face 及其下载域名。识别任务逐阶段运行，释放模型进程后再加载下一模型。

## 第一次使用

1. 打开“模型与服务”，选择 DeepSeek 或 Qwen，配置对应 API Key；配置 MiniMax Key、服务区域与音色。Mac Key 保存在系统钥匙串，留空保存会保留已有密钥。
2. 导入视频，等待预览及音频准备。点击“开始识别”，也可直接导入 UTF-8 SRT 文件。
3. 原文和译文输入框离开焦点时自动保存。修改原文而未同时修改译文时，清除该句旧译文和配音，避免沿用过期内容。点击时间定位视频；编辑按钮调整时间；更多操作支持拆分和合并。超过 20 秒或配音过长的字幕会标记。
4. 可选中单条字幕，用 Whisper 补识别。候选结果保留供人工比较，点击“采用”才替换原文。
5. 翻译按 25 条分批，携带前文与术语表；默认跳过已有译文，勾选字幕可重译。中文 SRT 导入要求条数与时间轴一致。
6. 先勾选几句生成配音并试听，再生成全部配音。相同文字、模型、音色、语速和服务区域复用已有音频；改变译文只失效该条配音。
7. 导出中文配音 MP4、原文/中文/双语 SRT，或独立配音 WAV。也可关闭“使用中文配音”，仅把字幕烧录到原视频。

音色 ID 可手填，也可保存 MiniMax Key 和区域后，点击“测试连接并读取音色”选择。国内和国际 Key 必须匹配相应区域。Qwen 同样有区域选项。

## 配音与时间轴

视频保留原始时长。配音短于字幕区间时补静音，超过时最多加速到 1.15×；仍无法容纳时报告具体字幕，要求精简译文或调整时间后重做，不会截断语句。字幕重叠会阻止配音合成。

默认替换原声。调高“原声音量”会同时保留原文人声和背景声；本版尚不支持把人声与背景音乐单独分离。SRT 可导出到 Subtitle Edit 精修后重新导入。

任务支持取消和重试。关闭服务后正在执行的任务标记为“中断”，需手动重试，已成功片段会复用。云端请求超时不会自动重复，以避免重复费用；收到 429 时进行有限重试。服务按其实际用量收费。

## Linux / 云环境开发

通用后端、界面、字幕导入、翻译、配音和 FFmpeg 可在 Linux 开发。MLX 本地识别仅在 Apple Silicon 上启用；Linux 不会伪装识别成功。Linux 的密钥使用进程环境变量，网页不会把密钥保存成明文文件：

```bash
# 从安全的环境配置注入这些变量；不要把真实值提交到 Git。
export DEEPSEEK_API_KEY=...
export QWEN_API_KEY=...
export MINIMAX_API_KEY=...
./scripts/install.sh
./scripts/start.sh
```

已有 API Key 缺失不影响使用导入的原文/中文 SRT 完成字幕编辑和保留原声的视频导出。

开发模式使用两个终端：

```bash
cd apps/api
uv run uvicorn move_app.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
cd apps/web
npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。前端请求通过 Vite 代理至后端；生产模式由 FastAPI 提供已构建的静态页面。服务默认只监听本机，不用于公网多用户部署。

## 验证

```bash
cd apps/api
uv run ruff check move_app tests
uv run pytest -q
cd ../web
npm run build
npx playwright install chromium
npm run test:e2e
```

后端集成测试用 FFmpeg 生成真实视频和音频，检查媒体准备、字幕校验、配音时间轴、缓存、导出、HTTP Range、取消与恢复。外部服务采用请求契约模拟，不会产生实际 API 费用。浏览器测试使用独立数据目录，执行真实上传、SRT 编辑、视频导出与下载。

Mac 上的 MLX 模型推理、实际内存/速度以及真实云端服务，需要在相应硬件和用户账号下另行验收；Linux 和模拟测试不代表这些检查已通过。

## 目录与配置

```text
apps/api/           FastAPI、SQLite、任务工作进程、服务适配器及测试
apps/web/           React + TypeScript 工作台及 Playwright 测试
workers/asr/        隔离的 MLX 识别环境
scripts/            安装、环境检查与 Mac 启动入口
.move/              本地项目、SQLite 和媒体产物（已忽略）
```

可选环境变量：`MOVE_DATA_DIR` 覆盖数据目录，`MOVE_MAX_UPLOAD_MB` 调整默认 2048 MB 上传限制，`MOVE_ASR_PYTHON` 指向其他识别环境，`MOVE_NO_OPEN=1` 禁止自动打开浏览器。安装脚本和服务不会自动加载 `.env`。

本机数据备份时请先停止服务，再复制完整 `.move` 目录。若改变数据位置或清理缓存，应先备份项目和原视频。原始视频、字幕、API Key 和生成音频不会被提交到仓库。

## 后续扩展

本地 IndexTTS 1.5、声音克隆、人声分离、多说话人、多项目批量处理尚未接入。现有配音适配层可扩展其他云端服务和独立本机 TTS 工作进程。

参考：[Parakeet MLX](https://github.com/senstella/parakeet-mlx)、[Whisper MLX](https://github.com/ml-explore/mlx-examples/tree/main/whisper)、[IndexTTS](https://github.com/index-tts/index-tts)、[MiniMax API 示例](https://github.com/MiniMax-AI/MiniMax-MCP)。
