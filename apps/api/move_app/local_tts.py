"""Isolated MLX worker, local voice references and cancellable settings-page tasks."""

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import config, db, media

MLX_LOCK = threading.Lock()
WORKER_VERSION = "mlx-audio-0.5.8-v1"


def model_dir() -> Path:
    return config.DATA / "models" / "qwen3-tts-0.6b-base"


def receipt() -> dict:
    try:
        value = json.loads((model_dir() / "ready.json").read_text())
        if value["model"] == config.TTS_MODEL and value["worker"] == WORKER_VERSION:
            if (
                value.get("revision")
                and (model_dir() / "config.json").is_file()
                and any(model_dir().glob("*.safetensors"))
                and (model_dir() / "speech_tokenizer/config.json").is_file()
                and any((model_dir() / "speech_tokenizer").glob("*.safetensors"))
            ):
                return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {}


def status() -> dict:
    supported = config.capabilities()["apple_silicon"]
    installed = supported and config.TTS_PYTHON.is_file()
    prepared = bool(receipt())
    return {
        "supported": supported,
        "runtime_installed": installed,
        "model_ready": installed and prepared,
        "model": config.TTS_MODEL,
        "note": (
            "Qwen3-TTS MLX 需要 Apple Silicon Mac"
            if not supported
            else "请在终端运行 ./scripts/install-tts.sh 安装独立配音环境"
            if not installed
            else "模型已下载并验证可加载；可上传参考音频进行试听"
            if prepared
            else "点击准备模型，首次下载需要网络和可用磁盘空间"
        ),
    }


def reference(reference_id: str) -> dict | None:
    with db.connect() as con:
        row = con.execute("SELECT * FROM voice_references WHERE id=?", (reference_id,)).fetchone()
    return dict(row) if row else None


def reference_path(reference_id: str) -> Path:
    # IDs come from SQLite, never from an unchecked upload filename.
    value = reference(reference_id)
    if not value:
        raise ValueError("请选择已上传的参考音频")
    return config.DATA / "references" / f"{value['id']}.wav"


def require_ready(settings: dict):
    value = status()
    if not value["model_ready"]:
        raise ValueError(value["note"])
    profile = reference(settings.get("reference_id", ""))
    if (
        not profile
        or not profile["transcript"].strip()
        or not reference_path(profile["id"]).is_file()
    ):
        raise ValueError("请在模型与服务中选择参考音频并填写对应文字")


def signature(text: str, settings: dict, include_speed=True) -> str:
    profile = reference(settings.get("reference_id", "")) or {}
    values = {
        "provider": settings.get("tts_provider", ""),
        "model": settings.get("tts_model", ""),
        "revision": receipt().get("revision", "unprepared"),
        "worker": WORKER_VERSION,
        "text": text,
        "reference_audio": profile.get("audio_hash", ""),
        "reference_text": profile.get("transcript", ""),
        "language": "chinese",
        "generation": {"temperature": 0.9, "max_tokens": 2048},
    }
    if include_speed:
        values["speed"] = settings["speed"]
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


@contextmanager
def exclusive(cancel, progress=None):
    if progress:
        progress(0, "等待本机模型资源；识别与配音串行运行")
    while not MLX_LOCK.acquire(timeout=0.2):
        media.check_cancel(cancel)
    try:
        media.check_cancel(cancel)
        yield
    finally:
        MLX_LOCK.release()


def worker(mode: str, values: dict, cancel, progress):
    require = status()
    if not require["runtime_installed"]:
        raise ValueError(require["note"])
    if mode == "prepare":
        (model_dir() / "ready.json").unlink(missing_ok=True)
    config.DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tts-", dir=config.DATA) as task:
        folder = Path(task)
        manifest = folder / "input.json"
        progress_file = folder / "progress.json"
        manifest.write_text(
            json.dumps(
                values
                | {
                    "model": config.TTS_MODEL,
                    "model_dir": str(model_dir()),
                    "worker": WORKER_VERSION,
                    "progress_file": str(progress_file),
                },
                ensure_ascii=False,
            )
        )
        environment = os.environ.copy()
        environment["HF_HOME"] = str(config.DATA / "huggingface")
        if mode != "prepare":
            environment["HF_HUB_OFFLINE"] = "1"
            environment["TRANSFORMERS_OFFLINE"] = "1"
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [
                    str(config.TTS_PYTHON),
                    str(config.ROOT / "workers/tts/synthesize.py"),
                    mode,
                    str(manifest),
                ],
                stdout=log,
                stderr=log,
                env=environment,
            )
            deadline = time.monotonic() + (7200 if mode == "prepare" else 86400)
            last = None
            try:
                while process.poll() is None:
                    media.check_cancel(cancel)
                    if time.monotonic() > deadline:
                        raise RuntimeError("本地配音处理超时，请取消后检查环境")
                    try:
                        value = json.loads(progress_file.read_text())
                        if value != last:
                            progress(
                                value.get("progress", 0), value.get("message", "本地模型处理中")
                            )
                            last = value
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.1)
                media.check_cancel(cancel)
                if process.returncode:
                    log.seek(0, 2)
                    size = log.tell()
                    log.seek(max(0, size - 2000))
                    details = log.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        "Qwen3-TTS 运行失败，请检查配音环境、模型和参考音频。" + details[-1200:]
                    )
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def generate(items: list[dict], settings: dict, cancel, progress):
    """Generate missing raw WAVs in a single model process for this batch."""
    require_ready(settings)
    profile = reference(settings["reference_id"])
    with exclusive(cancel, progress):
        worker(
            "generate",
            {
                "reference_audio": str(reference_path(profile["id"])),
                "reference_text": profile["transcript"],
                "items": items,
            },
            cancel,
            progress,
        )
    for item in items:
        if media.probe(Path(item["path"]))["duration"] <= 0:
            raise ValueError("本地模型未生成有效音频，请重新试听")


def apply_speed(source: Path, output: Path, speed: float, cancel):
    temporary = output.with_suffix(".tmp.wav")
    try:
        media.ffmpeg(
            [
                "-i",
                str(source),
                "-af",
                f"atempo={speed:.6f}",
                "-ar",
                "24000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(temporary),
            ],
            cancel,
        )
        if media.probe(temporary)["duration"] <= 0:
            raise ValueError("语速处理未生成有效音频")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


class Tools:
    """One background preparation/preview at a time; no project is needed."""

    def __init__(self):
        self.guard = threading.Lock()
        self.task = None
        self.cancel = threading.Event()
        self.thread = None

    def snapshot(self):
        with self.guard:
            return dict(self.task) if self.task else None

    def start(self, action, settings=None, text=""):
        with self.guard:
            if self.task and self.task["status"] in {"queued", "running", "cancelling"}:
                raise ValueError("请等待或取消当前模型准备／试听任务")
            self.cancel = threading.Event()
            self.task = {
                "id": db.uid(),
                "action": action,
                "status": "queued",
                "progress": 0,
                "message": "等待处理",
                "error": None,
                "audio_url": None,
            }
            value = dict(self.task)
            self.thread = threading.Thread(
                target=self.run, args=(action, settings, text), daemon=True
            )
            self.thread.start()
            return value

    def update(self, **values):
        with self.guard:
            self.task.update(values)

    def run(self, action, settings, text):
        def progress(value, message):
            self.update(status="running", progress=value, message=message)

        try:
            if action == "prepare":
                with exclusive(self.cancel, progress):
                    worker("prepare", {}, self.cancel, progress)
                if not receipt():
                    raise ValueError("模型加载验证未完成，请重新准备模型")
            else:
                folder = config.DATA / "tts-previews"
                folder.mkdir(exist_ok=True)
                raw = folder / f"{signature(text, settings, False)}.raw.wav"
                output = folder / f"{self.task['id']}.wav"
                if not raw.exists():
                    generate([{"text": text, "path": str(raw)}], settings, self.cancel, progress)
                apply_speed(raw, output, settings["speed"], self.cancel)
                self.update(audio_url=f"/api/tts/previews/{self.task['id']}")
            media.check_cancel(self.cancel)
            self.update(
                status="completed",
                progress=1,
                message="模型准备完成" if action == "prepare" else "测试配音已生成",
            )
        except media.Cancelled:
            self.update(status="cancelled", message="已取消")
        except Exception as exc:
            self.update(status="failed", error=str(exc)[:2000], message="处理失败，可重试")

    def stop(self):
        self.cancel.set()
        if self.thread:
            self.thread.join(timeout=5)
