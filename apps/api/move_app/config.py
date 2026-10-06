import os
import platform
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = Path(os.environ.get("MOVE_DATA_DIR", ROOT / ".move")).resolve()
ASR_PYTHON = Path(os.environ.get("MOVE_ASR_PYTHON", ROOT / "workers/asr/.venv/bin/python"))


def capabilities() -> dict:
    apple = platform.system() == "Darwin" and platform.machine() == "arm64"
    return {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "asr": apple and ASR_PYTHON.is_file(),
        "apple_silicon": apple,
        "asr_note": "已安装 Mac 识别环境"
        if apple and ASR_PYTHON.is_file()
        else (
            "运行 scripts/install-asr.sh 安装识别模型环境"
            if apple
            else "MLX 识别需要 Apple Silicon Mac；此机器可使用导入的 SRT"
        ),
    }
