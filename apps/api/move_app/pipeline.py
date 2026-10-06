import hashlib
import json
import math
import queue
import threading
from pathlib import Path

from . import config, db, media, providers


def directory(project_id: str) -> Path:
    return config.DATA / "projects" / project_id


def audio_hash(cue: dict, settings: dict) -> str:
    values = {key: settings[key] for key in ["voice_id", "speed", "tts_model", "tts_region"]}
    values["text"] = cue["translation"]
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class Runner:
    def __init__(self):
        self.queue = queue.Queue()
        self.events: dict[str, threading.Event] = {}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True, name="move-worker")

    def start(self):
        with db.connect() as con:
            con.execute(
                "UPDATE jobs SET status='interrupted',message='服务重启，已完成片段保留；可手动重试',updated=? "
                "WHERE status IN ('running','cancelling')",
                (db.now(),),
            )
            queued = list(con.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created"))
        for row in queued:
            self.submit(row["id"])
        self.thread.start()

    def close(self):
        self.stop.set()
        for event in list(self.events.values()):
            event.set()
        self.queue.put(None)
        self.thread.join(timeout=5)

    def submit(self, job_id: str):
        self.events[job_id] = threading.Event()
        self.queue.put(job_id)

    def cancel(self, job_id: str):
        event = self.events.get(job_id)
        if event:
            event.set()
        with db.connect() as con:
            row = con.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row and row["status"] in {"queued", "running", "cancelling"}:
                status = "cancelled" if row["status"] == "queued" else "cancelling"
                con.execute(
                    "UPDATE jobs SET status=?,message='正在取消；正在进行的服务请求需等待返回',updated=? WHERE id=?",
                    (status, db.now(), job_id),
                )

    def loop(self):
        while not self.stop.is_set():
            job_id = self.queue.get()
            if job_id is None:
                break
            with db.connect() as con:
                row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["status"] != "queued":
                self.events.pop(job_id, None)
                continue
            cancel = self.events[job_id]
            db.update_job(job_id, status="running", message="开始处理", error=None)
            try:
                self.execute(dict(row), cancel)
                media.check_cancel(cancel)
                db.update_job(job_id, status="completed", progress=1, message="处理完成")
            except media.Cancelled:
                db.update_job(
                    job_id,
                    status="interrupted" if self.stop.is_set() else "cancelled",
                    message="服务停止，已完成片段保留"
                    if self.stop.is_set()
                    else "已取消，已完成片段保留",
                )
            except Exception as exc:
                # Provider errors never include response bodies, headers or credential values.
                db.update_job(
                    job_id, status="failed", error=str(exc)[:3000], message="处理失败，可重试"
                )
            finally:
                self.events.pop(job_id, None)

    def execute(self, job: dict, cancel):
        payload = json.loads(job["payload"])
        project_id, stage = job["project_id"], job["stage"]
        project = db.project(project_id)
        folder = directory(project_id)
        settings = payload["settings"]

        def progress(value, message):
            media.check_cancel(cancel)
            db.update_job(job["id"], progress=value, message=message)

        if stage == "prepare":
            progress(0.1, "准备浏览器预览")
            preview = folder / "preview.tmp.mp4"
            codec = project["metadata"]["codec"]
            arguments = [
                "-i",
                str(folder / "source"),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "copy" if codec == "h264" else "libx264",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(preview),
            ]
            media.ffmpeg(arguments, cancel, timeout=max(1800, project["metadata"]["duration"] * 10))
            preview.replace(folder / "preview.mp4")
            if project["metadata"]["has_audio"]:
                progress(0.6, "提取音频与波形")
                temp = folder / "audio.tmp.wav"
                media.ffmpeg(
                    ["-i", str(folder / "source"), "-vn", "-ac", "1", "-ar", "16000", str(temp)],
                    cancel,
                )
                temp.replace(folder / "audio.wav")
                (folder / "waveform.json").write_text(json.dumps(media.peaks(folder / "audio.wav")))
            return

        if stage in {"transcribe", "retranscribe"}:
            if not config.capabilities()["asr"]:
                raise ValueError(config.capabilities()["asr_note"])
            if not (folder / "audio.wav").exists():
                raise ValueError("视频没有可识别的音频，或音频准备尚未完成")
            progress(0.1, "加载识别模型；首次运行会下载模型，请保持网络连接")
            source = folder / "audio.wav"
            offset = 0.0
            selected = None
            if stage == "retranscribe":
                selected = next(
                    (c for c in db.cues(project_id) if c["id"] in payload["cue_ids"]), None
                )
                if not selected:
                    raise ValueError("请选择一条字幕补识别")
                offset = max(0, selected["start"] - 0.5)
                source = folder / "clip.wav"
                media.ffmpeg(
                    [
                        "-ss",
                        str(offset),
                        "-i",
                        str(folder / "audio.wav"),
                        "-t",
                        str(selected["end"] - offset + 0.5),
                        str(source),
                    ],
                    cancel,
                )
            output = folder / f"asr-{job['id']}.json"
            media.run(
                [
                    str(config.ASR_PYTHON),
                    str(config.ROOT / "workers/asr/transcribe.py"),
                    str(source),
                    str(output),
                    "--engine",
                    "whisper" if selected else "parakeet",
                ],
                cancel,
                timeout=max(3600, project["metadata"]["duration"] * 15),
            )
            values = json.loads(output.read_text(encoding="utf-8"))
            values = [c for c in values if c.get("original", "").strip()]
            if not values:
                raise ValueError("未识别出语音，请检查片段和语言")
            for cue in values:
                if not all(math.isfinite(cue.get(key, float("nan"))) for key in ["start", "end"]):
                    raise ValueError("识别结果包含无效时间轴")
                cue["start"] = max(0, cue["start"] + offset)
                cue["end"] = min(project["metadata"]["duration"], cue["end"] + offset)
            values = [c for c in values if c["end"] > c["start"]]
            if selected:
                # Store a candidate: human review chooses whether to replace existing subtitles.
                output.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
                progress(0.95, "候选结果已生成，请比较并选择采用")
            else:
                db.replace_cues(project_id, values)
            return

        cues = db.cues(project_id)
        selected_ids = set(payload.get("cue_ids", []))
        selected = [c for c in cues if not selected_ids or c["id"] in selected_ids]
        if not selected:
            raise ValueError("没有可处理的字幕")
        if stage == "translate":
            selected = [c for c in selected if payload.get("force") or not c["translation"]]
            for offset in range(0, len(selected), 25):
                progress(
                    offset / max(1, len(selected)),
                    f"翻译 {offset + 1}–{min(offset + 25, len(selected))} / {len(selected)}",
                )
                batch = selected[offset : offset + 25]
                context = [c for c in cues if c["start"] < batch[0]["start"]][-5:]
                values = providers.translate(batch, context, settings, cancel)
                media.check_cancel(cancel)
                with db.connect() as con:
                    for cue in batch:
                        con.execute(
                            "UPDATE cues SET translation=?,revision=revision+1,audio_hash=NULL,"
                            "audio_duration=NULL,audio_file=NULL WHERE id=?",
                            (values[cue["id"]], cue["id"]),
                        )
                    db.changed(con, project_id)
            return
        if stage == "dub":
            if any(not c["translation"].strip() for c in selected):
                raise ValueError("请先翻译或填写选中字幕的中文文字")
            (folder / "segments").mkdir(exist_ok=True)
            for i, cue in enumerate(selected):
                progress(i / len(selected), f"配音 {i + 1} / {len(selected)}；已完成片段自动复用")
                signature = audio_hash(cue, settings)
                name = f"segments/{signature}.mp3"
                path = folder / name
                if not path.exists():
                    audio = providers.synthesize(cue["translation"], settings, cancel)
                    temp = path.with_suffix(".tmp.mp3")
                    temp.write_bytes(audio)
                    duration = media.probe(temp)["duration"]
                    if duration <= 0:
                        temp.unlink(missing_ok=True)
                        raise ValueError("配音服务返回不可播放的音频")
                    temp.replace(path)
                duration = media.probe(path)["duration"]
                with db.connect() as con:
                    con.execute(
                        "UPDATE cues SET audio_hash=?,audio_duration=?,audio_file=? WHERE id=?",
                        (signature, duration, name, cue["id"]),
                    )
                    # Audio changes invalidate an existing export too.
                    db.changed(con, project_id)
            return
        if stage == "export":
            self.export(project, cues, folder, payload, cancel, progress)
            return
        raise ValueError("未知处理阶段")

    def export(self, project, cues, folder, payload, cancel, progress):
        mode = payload.get("subtitle_mode", "bilingual")
        settings = payload["settings"]
        if mode in {"translated", "bilingual"} and any(not c["translation"].strip() for c in cues):
            raise ValueError("存在未翻译字幕，请补全译文或选择原文字幕")
        duration = project["metadata"]["duration"]
        if any(c["end"] > duration + 0.05 for c in cues):
            raise ValueError("字幕超出视频时长，请调整时间轴")
        progress(0.05, "检查配音与时间轴")
        if payload.get("use_dubbing", True):
            import array
            import wave

            sample_rate = 24000
            # Only one decoded cue resides in memory, even for long videos.
            temp_dub = folder / "dubbing.tmp.wav"
            with wave.open(str(temp_dub), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                position = 0
                for i, cue in enumerate(cues):
                    media.check_cancel(cancel)
                    if cue["audio_hash"] != audio_hash(cue, settings) or not cue["audio_file"]:
                        raise ValueError(f"第 {i + 1} 条配音缺失或设置已更改，请重新配音")
                    available = (
                        min(cue["end"], cues[i + 1]["start"] if i + 1 < len(cues) else duration)
                        - cue["start"]
                    )
                    if available <= 0:
                        raise ValueError(f"第 {i + 1} 条字幕与下一条重叠，请调整时间轴")
                    speed = max(1.0, cue["audio_duration"] / available)
                    if speed > 1.15 + 0.001:
                        raise ValueError(
                            f"第 {i + 1} 条配音过长，需要 {speed:.2f} 倍速。请精简译文或调整时间轴后重配音"
                        )
                    pcm = folder / "aligned.wav"
                    media.ffmpeg(
                        [
                            "-i",
                            str(folder / cue["audio_file"]),
                            "-af",
                            f"atempo={speed:.6f}",
                            "-ar",
                            str(sample_rate),
                            "-ac",
                            "1",
                            "-c:a",
                            "pcm_s16le",
                            str(pcm),
                        ],
                        cancel,
                    )
                    with wave.open(str(pcm), "rb") as clip:
                        samples = array.array("h", clip.readframes(clip.getnframes()))
                    start = round(cue["start"] * sample_rate)
                    if start < position:
                        raise ValueError("对齐后配音发生重叠，请调整字幕时间")
                    write_silence(output, start - position, cancel)
                    output.writeframes(samples.tobytes())
                    position = start + len(samples)
                    progress(0.1 + 0.4 * (i + 1) / len(cues), f"对齐配音 {i + 1} / {len(cues)}")
                write_silence(output, max(0, round(duration * sample_rate) - position), cancel)
        metadata = project["metadata"]
        (folder / "subtitle.ass").write_text(
            media.ass(cues, mode, metadata["width"], metadata["height"]), encoding="utf-8"
        )
        arguments = ["-i", str(folder / "source")]
        if payload.get("use_dubbing", True):
            arguments += ["-i", str(folder / "dubbing.tmp.wav")]
            if payload.get("original_volume", 0) > 0 and metadata["has_audio"]:
                arguments += [
                    "-filter_complex",
                    f"[0:a]volume={payload['original_volume']}[original];"
                    "[original][1:a]amix=inputs=2:duration=longest:normalize=0[a]",
                    "-map",
                    "0:v:0",
                    "-map",
                    "[a]",
                ]
            else:
                arguments += ["-map", "0:v:0", "-map", "1:a:0"]
        else:
            arguments += ["-map", "0:v:0", "-map", "0:a:0?"]
        if mode != "none":
            arguments += ["-vf", "ass=subtitle.ass"]
        arguments += [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-t",
            str(duration),
            "-movflags",
            "+faststart",
            "output.tmp.mp4",
        ]
        progress(0.6, "合成视频；请等待编码完成")
        media.ffmpeg(arguments, cancel, cwd=folder, timeout=max(1800, duration * 15))
        result = media.probe(folder / "output.tmp.mp4")
        if abs(result["duration"] - duration) > 0.5:
            raise ValueError("导出时长检查失败，未替换已有输出")
        (folder / "output.tmp.mp4").replace(folder / "output.mp4")
        if payload.get("use_dubbing", True):
            (folder / "dubbing.tmp.wav").replace(folder / "dubbing.wav")
        with db.connect() as con:
            con.execute(
                "UPDATE projects SET export_revision=subtitle_revision,export_signature=?,updated=? WHERE id=?",
                (json.dumps(settings, sort_keys=True), db.now(), project["id"]),
            )


def write_silence(output, frames, cancel):
    while frames > 0:
        media.check_cancel(cancel)
        count = min(frames, 24000)
        output.writeframes(b"\0\0" * count)
        frames -= count
