# Move · 视频翻译工作台

在 Apple Silicon Mac 本机运行的中文视频翻译工具。用浏览器完成 **导入视频 → 识别字幕 → 校对 → 翻译 → 试听配音 → 导出**。媒体文件保存在本机，翻译在你主动启动任务时调用云端服务，中文配音由本机 Qwen3-TTS MLX 完成。

首版面向 M1 Pro / 16 GB 的英文视频转中文场景：Parakeet MLX 识别、Whisper MLX 局部补识别、DeepSeek / Qwen 翻译、Qwen3-TTS 0.6B Base MLX 参考音频配音、FFmpeg 合成。

## Mac 安装与启动

需要 Apple Silicon Mac（macOS 14 或更新版本）、Python 3.11–3.13、Node.js 22.12+ 或 24，以及带 libx264 / libass 的 FFmpeg。推荐先安装 [Homebrew](https://brew.sh)，再运行：

```bash
brew install uv node ffmpeg
git clone https://github.com/haichao80855/move.git
cd move
./scripts/install.sh
./scripts/install-asr.sh
./scripts/install-tts.sh
./scripts/start.sh
```

`uv` 会使用符合版本要求的 Python（必要时下载）。启动后打开 `http://127.0.0.1:8000`。也可在 Finder 双击 `start.command`。关闭终端或按 Ctrl+C 停止服务；已完成的项目和片段保留。

识别模型在第一次使用时下载至 Hugging Face 缓存；安装脚本不会提前下载大型权重。首次识别需要访问 Hugging Face 及其下载域名。识别任务逐阶段运行，释放模型进程后再加载下一模型。

## 第一次使用

1. 打开“模型与服务”，选择 DeepSeek 或 Qwen，配置对应 API Key。DeepSeek 的“测试连接”直接使用当前输入的 Key 和模型，留空 Key 使用环境变量／钥匙串中的已有密钥，无需先保存；显示耗时及凭据、模型、限流、超时等错误。测试只发送一次极短请求，可能产生少量费用，不自动重试，也不保存未提交的 Key。Mac Key 保存在系统钥匙串，留空保存会保留已有密钥。
2. 导入视频，等待预览及音频准备。点击“开始识别”，也可直接导入 UTF-8 SRT 文件。
3. 原文和译文输入框离开焦点时自动保存。修改原文而未同时修改译文时，清除该句旧译文和配音，避免沿用过期内容。点击时间定位视频；编辑按钮调整时间；更多操作支持拆分和合并。超过 20 秒或配音过长的字幕会标记。
4. 可选中单条字幕，用 Whisper 补识别。候选结果保留供人工比较，点击“采用”才替换原文。
5. 翻译按 25 条分批，携带前文与术语表；默认跳过已有译文，勾选字幕可重译。中文 SRT 导入要求条数与时间轴一致。
6. 先勾选几句生成配音并试听，再生成全部配音。相同文字、模型版本、参考音频及参考文字复用原始 WAV；只改变语速时使用 FFmpeg 重新处理，保持音高，不重复模型推理。改变译文只失效该条配音。
7. 导出中文配音 MP4、原文/中文/双语 SRT，或独立配音 WAV。也可关闭“使用中文配音”，仅把字幕烧录到原视频。

### 本地配音准备与试听

1. 运行 `./scripts/install-tts.sh` 安装隔离的配音环境，固定 `mlx-audio==0.5.8`，不会改动字幕识别环境。
2. 在“模型与服务”的本地配音卡片点击“下载并准备模型”。使用 **`mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16`**，下载权重、文本 tokenizer 与语音编码器，并验证模型可以加载。首次需要访问 Hugging Face 及其下载域名；可以取消并重新准备。
3. 上传 3–30 秒、20 MB 以内的参考音频（推荐 5–15 秒、清晰单人语音），逐字填写音频中的原话。WAV、MP3、M4A、FLAC 等由 FFmpeg 校验并规范成单声道 24 kHz WAV，保存在本机。已有参考文字可单独校对保存。
4. 点击“生成测试配音”，使用当前选中的参考音频、测试文字和语速，播放生成的音频，无需先保存设置。**模型可加载和实际语音生成成功是两个不同状态**，请用试听确认效果。
5. 满意后保存设置，项目中的“生成配音”会使用这份参考音频。Base 没有预设音色，必须同时提供参考音频和对应文字，也不需要配音 API Key。

模型保存在 `.move/models/qwen3-tts-0.6b-base`，参考音频在 `.move/references`。准备完成后，生成进程以离线模式加载本地权重；每批字幕只加载一次模型，完成或取消后释放进程。识别、模型准备和配音共用串行限制，适配 16 GB Mac。修改参考文字会使关联配音及导出结果标记为过期。历史项目、音频和已保存的钥匙串条目保留；旧云端配音任务需准备本地模型后手动重试。

Qwen 翻译仍使用云端 API 和区域选项，与本地 Qwen3-TTS 配音独立。

## 配音与时间轴

视频保留原始时长。配音短于字幕区间时补静音，超过时最多加速到 1.15×；仍无法容纳时报告具体字幕，要求精简译文或调整时间后重做，不会截断语句。字幕重叠会阻止配音合成。

默认替换原声。调高“原声音量”会同时保留原文人声和背景声；本版尚不支持把人声与背景音乐单独分离。SRT 可导出到 Subtitle Edit 精修后重新导入。

任务支持取消和重试。关闭服务后正在执行的任务标记为“中断”，需手动重试，已成功片段会复用。云端请求超时不会自动重复，以避免重复费用；收到 429 时进行有限重试。云端翻译服务按其实际用量收费。

## Linux / 云环境开发

通用后端、界面、字幕导入、翻译与 FFmpeg 可在 Linux 开发。MLX 本地识别和配音仅在 Apple Silicon 上启用；Linux 会明确显示不支持。Linux 的翻译密钥使用进程环境变量，网页不会把密钥保存成明文文件；DeepSeek 输入框可临时测试 Key，保存设置不会在 Linux 持久化这个临时 Key：

```bash
# 从安全的环境配置注入这些变量；不要把真实值提交到 Git。
export DEEPSEEK_API_KEY=...
export QWEN_API_KEY=...
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

后端集成测试用 FFmpeg 生成真实视频和音频，检查媒体准备、字幕校验、配音时间轴、缓存、语速后处理、参考音频校验、导出、HTTP Range、取消与恢复。外部服务采用请求契约模拟，不会产生实际 API 费用。浏览器测试使用独立数据目录，执行真实上传、SRT 编辑、视频导出与下载，以及 DeepSeek 未保存配置测试、模型状态和参考音频上传／试听页面流程。模型下载和推理在云端测试中模拟。

Mac 上的 MLX 模型推理、实际内存/速度以及真实云端服务，需要在相应硬件和用户账号下另行验收；Linux 和模拟测试不代表这些检查已通过。

Mac 验收建议：准备模型 → 上传真实参考语音及准确原话 → 生成并试听测试配音 → 给 2–3 条中文字幕配音 → 修改语速确认复用原始片段 → 导出视频检查时间轴。准备完成后断网再次生成测试配音，验证本地权重可用；同时用活动监视器观察 M1 Pro / 16 GB 的内存与耗时。

## 目录与配置

```text
apps/api/           FastAPI、SQLite、任务工作进程、服务适配器及测试
apps/web/           React + TypeScript 工作台及 Playwright 测试
workers/asr/        隔离的 MLX 识别环境
workers/tts/        隔离的 Qwen3-TTS MLX 配音环境
scripts/            安装、环境检查与 Mac 启动入口
.move/              本地项目、SQLite 和媒体产物（已忽略）
```

可选环境变量：`MOVE_DATA_DIR` 覆盖数据目录，`MOVE_MAX_UPLOAD_MB` 调整默认 2048 MB 上传限制，`MOVE_ASR_PYTHON` 指向其他识别环境，`MOVE_TTS_PYTHON` 指向其他配音环境，`MOVE_NO_OPEN=1` 禁止自动打开浏览器。安装脚本和服务不会自动加载 `.env`。

本机数据备份时请先停止服务，再复制完整 `.move` 目录。若改变数据位置或清理缓存，应先备份项目和原视频。原始视频、字幕、API Key 和生成音频不会被提交到仓库。

## 后续扩展

人声分离、多说话人、多项目批量处理尚未接入。当前本地配音支持单份参考音频用于整个项目。

参考：[Parakeet MLX](https://github.com/senstella/parakeet-mlx)、[Whisper MLX](https://github.com/ml-explore/mlx-examples/tree/main/whisper)、[MLX Audio](https://github.com/Blaizzy/mlx-audio)、[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)。
