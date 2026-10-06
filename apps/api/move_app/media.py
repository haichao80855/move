import json
import math
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from threading import Event


def peaks(path: Path) -> dict:
    import array

    values = []
    with wave.open(str(path), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        block = max(1, math.ceil(audio.getnframes() / 1600))
        while data := audio.readframes(block):
            samples = array.array("h", data)
            values.append(round(max((abs(value) for value in samples), default=0) / 32768, 4))
    return {"duration": duration, "peaks": values}


class Cancelled(Exception):
    pass


def check_cancel(cancel: Event):
    if cancel.is_set():
        raise Cancelled("任务已取消")


def run(command: list[str], cancel: Event, cwd: Path | None = None, timeout: float = 1800):
    check_cancel(cancel)
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=log)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic() > deadline:
                    raise RuntimeError("媒体处理超时，请缩短视频或检查 FFmpeg")
                time.sleep(0.1)
            if process.returncode:
                log.seek(0, 2)
                size = log.tell()
                log.seek(max(0, size - 2500))
                raise RuntimeError(log.read().decode("utf-8", errors="replace"))
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "duration": float(data.get("format", {}).get("duration", 0)),
        "width": video.get("width", 0),
        "height": video.get("height", 0),
        "codec": video.get("codec_name", ""),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def ffmpeg(arguments: list[str], cancel: Event, cwd: Path | None = None, timeout=1800):
    run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments],
        cancel,
        cwd,
        timeout,
    )


STAMP = re.compile(r"^(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})$")


def parse_time(value: str) -> float:
    match = STAMP.fullmatch(value.strip())
    if not match:
        raise ValueError(f"无效字幕时间：{value[:40]}")
    hour, minute, second, millis = map(int, match.groups())
    if minute >= 60 or second >= 60:
        raise ValueError("字幕时间中的分、秒必须小于 60")
    return hour * 3600 + minute * 60 + second + millis / 1000


def parse_srt(text: str) -> list[dict]:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    values = []
    for block in re.split(r"\n[ \t]*\n", text):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines or " --> " not in lines[0]:
            raise ValueError("请导入包含序号、时间轴和文字的有效 SRT 文件")
        start_text, end_text = lines[0].split(" --> ", 1)
        start, end = parse_time(start_text), parse_time(end_text.split()[0])
        content = "\n".join(lines[1:]).strip()
        if end <= start or not content:
            raise ValueError("字幕结束时间必须晚于开始时间，文字不能为空")
        values.append({"start": start, "end": end, "original": content})
    if not values or len(values) > 30000:
        raise ValueError("SRT 必须包含 1–30000 条字幕")
    return sorted(values, key=lambda c: c["start"])


def timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hour, millis = divmod(millis, 3600000)
    minute, millis = divmod(millis, 60000)
    second, millis = divmod(millis, 1000)
    return f"{hour:02}:{minute:02}:{second:02},{millis:03}"


def srt(cues: list[dict], mode: str) -> str:
    blocks = []
    for i, cue in enumerate(cues, 1):
        content = cue["original"] if mode == "original" else cue["translation"]
        if mode == "bilingual":
            content = "\n".join(t for t in [cue["translation"], cue["original"]] if t)
        blocks.append(f"{i}\n{timestamp(cue['start'])} --> {timestamp(cue['end'])}\n{content}\n")
    return "\n".join(blocks)


def ass(cues: list[dict], mode: str, width=1920, height=1080) -> str:
    font_size = max(20, round(height * 0.043))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,{font_size},&H00FFFFFF,&H00FFFFFF,&H00161616,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,35,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def stamp(t):
        return timestamp(t).replace(",", ".")[:-1]

    for cue in cues:
        text = cue["original"] if mode == "original" else cue["translation"]
        if mode == "bilingual":
            text = "\n".join(x for x in [cue["translation"], cue["original"]] if x)
        text = text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", r"\N")
        header += f"Dialogue: 0,{stamp(cue['start'])},{stamp(cue['end'])},Default,,0,0,0,,{text}\n"
    return header
