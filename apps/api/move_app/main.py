import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, local_tts, media, providers
from .pipeline import Runner, audio_hash, directory, export_signature


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.initialize()
    app.state.tts_tools = local_tts.Tools()
    app.state.runner = Runner()
    app.state.runner.start()
    yield
    app.state.runner.close()
    app.state.tts_tools.stop()


app = FastAPI(title="Move · 视频翻译工作台", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Validation failures must not reflect an unsaved test key in the response.
    if request.url.path == "/api/services/deepseek/test":
        return JSONResponse(status_code=422, content={"detail": "请输入有效的模型名称和 API Key"})
    return await request_validation_exception_handler(request, exc)


origins = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def local_access(request: Request, call_next):
    # Reject DNS rebinding and cross-origin writes to a local application.
    if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
        return Response("Local access only", status_code=403)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return Response("Origin rejected", status_code=403)
    return await call_next(request)


def require_project(project_id: str) -> dict:
    value = db.project(project_id)
    if not value:
        raise HTTPException(404, "项目不存在")
    return value


def idle(project_id: str):
    with db.connect() as con:
        if con.execute(
            "SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running','cancelling')",
            (project_id,),
        ).fetchone():
            raise HTTPException(409, "项目正在处理，请完成或取消当前任务后编辑")


@contextmanager
def editing(project_id: str):
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute(
            "SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running','cancelling')",
            (project_id,),
        ).fetchone():
            raise HTTPException(409, "项目正在处理，请完成或取消当前任务后编辑")
        yield con


def cue_times(start: float, end: float, duration: float):
    if (
        not math.isfinite(start)
        or not math.isfinite(end)
        or not 0 <= start < end <= duration + 0.05
    ):
        raise HTTPException(422, "字幕时间必须满足 0 ≤ 开始 < 结束 ≤ 视频时长")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/system")
def system():
    return config.capabilities()


@app.get("/api/settings")
def settings():
    return db.settings() | {
        "credentials": {p: bool(providers.credential(p)) for p in providers.ENV_KEYS}
    }


class SettingsUpdate(BaseModel):
    translation_provider: Literal["deepseek", "qwen"] = "deepseek"
    deepseek_model: str = Field(default="deepseek-chat", min_length=1, max_length=100)
    qwen_model: str = Field(default="qwen-plus", min_length=1, max_length=100)
    qwen_region: Literal["cn", "global"] = "cn"
    tts_provider: Literal["qwen3_mlx"] = "qwen3_mlx"
    tts_model: Literal[config.TTS_MODEL] = config.TTS_MODEL
    reference_id: str = Field(default="", max_length=32)
    speed: float = Field(default=1, ge=0.5, le=2)
    glossary: str = Field(default="", max_length=10000)
    translation_style: str = Field(default=db.DEFAULTS["translation_style"], max_length=3000)
    keys: dict[Literal["deepseek", "qwen", "minimax"], str] = Field(default_factory=dict)


@app.put("/api/settings")
def put_settings(values: SettingsUpdate):
    if values.reference_id and not local_tts.reference(values.reference_id):
        raise HTTPException(400, "请选择有效的参考音频")
    try:
        for provider, key in values.keys.items():
            if len(key) > 1000:
                raise ValueError("密钥长度无效")
            providers.save_credential(provider, key.strip())
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(400, str(exc)) from exc
        raise HTTPException(400, "系统钥匙串无法保存密钥，请检查系统权限或使用环境变量") from exc
    db.save_settings(values.model_dump(exclude={"keys"}))
    return settings()


class DeepSeekTest(BaseModel):
    model: str = Field(min_length=1, max_length=100)
    key: str = Field(default="", max_length=1000, repr=False)


@app.post("/api/services/deepseek/test")
def deepseek_test(values: DeepSeekTest):
    return providers.test_deepseek(values.model.strip(), values.key)


@app.get("/api/tts/status")
def tts_status(request: Request):
    return local_tts.status() | {"task": request.app.state.tts_tools.snapshot()}


@app.post("/api/tts/prepare", status_code=202)
def prepare_tts(request: Request):
    if not local_tts.status()["runtime_installed"]:
        raise HTTPException(400, local_tts.status()["note"])
    with db.connect() as con:
        if con.execute(
            "SELECT 1 FROM jobs WHERE stage IN ('dub','export','transcribe','retranscribe') "
            "AND status IN ('queued','running','cancelling')"
        ).fetchone():
            raise HTTPException(409, "请先完成或取消当前识别、配音与导出任务，再准备模型")
    try:
        return request.app.state.tts_tools.start("prepare")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/tts/cancel")
def cancel_tts(request: Request):
    tools = request.app.state.tts_tools
    task = tools.snapshot()
    if task and task["status"] in {"queued", "running", "cancelling"}:
        tools.cancel.set()
    return {"ok": True}


def public_reference(value: dict):
    return value | {"audio_url": f"/api/tts/references/{value['id']}/audio"}


@app.get("/api/tts/references")
def list_references():
    with db.connect() as con:
        return [
            public_reference(dict(row))
            for row in con.execute("SELECT * FROM voice_references ORDER BY created DESC")
        ]


@app.post("/api/tts/references", status_code=201)
async def upload_reference(file: UploadFile = File(...), transcript: str = Form(...)):
    transcript = transcript.strip()
    if not 1 <= len(transcript) <= 2000:
        raise HTTPException(422, "请填写与参考音频一致的文字（1–2000 字）")
    folder = config.DATA / "references"
    folder.mkdir(parents=True, exist_ok=True)
    reference_id = db.uid()
    source, output = folder / f"{reference_id}.upload", folder / f"{reference_id}.wav"
    try:
        size = 0
        with source.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 20 * 1024 * 1024:
                    raise HTTPException(413, "参考音频不能超过 20 MB")
                target.write(chunk)
        metadata = await asyncio.to_thread(media.probe, source)
        if not metadata["has_audio"] or not 3 <= metadata["duration"] <= 30:
            raise HTTPException(400, "请上传 3–30 秒的有效参考音频，推荐 5–15 秒清晰单人语音")
        await asyncio.to_thread(
            media.ffmpeg,
            [
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            threading.Event(),
            timeout=60,
        )
        name = (file.filename or "参考音频").replace("\\", "/").split("/")[-1][:200]
        with db.connect() as con:
            con.execute(
                "INSERT INTO voice_references(id,name,transcript,audio_hash,duration,created) VALUES(?,?,?,?,?,?)",
                (
                    reference_id,
                    name,
                    transcript,
                    hashlib.sha256(output.read_bytes()).hexdigest(),
                    media.probe(output)["duration"],
                    db.now(),
                ),
            )
    except HTTPException:
        output.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output.unlink(missing_ok=True)
        raise HTTPException(
            400, "参考音频无法解码，请使用有效的 WAV、MP3、M4A 或 FLAC 文件"
        ) from exc
    finally:
        source.unlink(missing_ok=True)
        await file.close()
    return public_reference(local_tts.reference(reference_id))


class ReferenceUpdate(BaseModel):
    transcript: str = Field(min_length=1, max_length=2000)


@app.put("/api/tts/references/{reference_id}")
def update_reference(reference_id: str, values: ReferenceUpdate, request: Request):
    if not local_tts.reference(reference_id):
        raise HTTPException(404, "参考音频不存在")
    if not values.transcript.strip():
        raise HTTPException(422, "参考文字不能为空")
    task = request.app.state.tts_tools.snapshot()
    if task and task["status"] in {"queued", "running", "cancelling"}:
        raise HTTPException(409, "请先完成或取消模型准备／试听任务，再修改参考文字")
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if con.execute(
            "SELECT 1 FROM jobs WHERE stage IN ('dub','export') AND status IN ('queued','running','cancelling') "
            "AND json_extract(payload,'$.settings.reference_id')=?",
            (reference_id,),
        ).fetchone():
            raise HTTPException(409, "此参考音频正在用于配音／导出，请完成任务后修改")
        con.execute(
            "UPDATE voice_references SET transcript=? WHERE id=?",
            (values.transcript.strip(), reference_id),
        )
    return public_reference(local_tts.reference(reference_id))


@app.get("/api/tts/references/{reference_id}/audio")
def reference_audio(reference_id: str):
    if not local_tts.reference(reference_id):
        raise HTTPException(404, "参考音频不存在")
    path = local_tts.reference_path(reference_id)
    if not path.is_file():
        raise HTTPException(404, "参考音频文件不存在")
    return FileResponse(path, media_type="audio/wav")


class TTSPreview(BaseModel):
    reference_id: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=300)
    speed: float = Field(default=1, ge=0.5, le=2)


@app.post("/api/tts/preview", status_code=202)
def preview_tts(values: TTSPreview, request: Request):
    settings = db.settings() | {"reference_id": values.reference_id, "speed": values.speed}
    if not values.text.strip():
        raise HTTPException(422, "请填写测试配音文字")
    try:
        local_tts.require_ready(settings)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        return request.app.state.tts_tools.start("preview", settings, values.text.strip())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/tts/previews/{preview_id}")
def preview_audio(preview_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", preview_id):
        raise HTTPException(404, "测试配音不存在")
    path = config.DATA / "tts-previews" / f"{preview_id}.wav"
    if not path.is_file():
        raise HTTPException(404, "测试配音尚未生成")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/projects")
def projects():
    with db.connect() as con:
        rows = list(con.execute("SELECT * FROM projects ORDER BY updated DESC"))
    result = []
    for row in rows:
        value = dict(row)
        value["metadata"] = json.loads(value["metadata"])
        all_cues = db.cues(value["id"])
        value["cue_count"] = len(all_cues)
        value["translated_count"] = sum(bool(c["translation"]) for c in all_cues)
        value["latest_job"] = next(iter(db.jobs(value["id"])), None)
        result.append(value)
    return result


@app.post("/api/projects", status_code=201)
async def upload(request: Request, file: UploadFile = File(...)):
    if not config.capabilities()["ffmpeg"] or not config.capabilities()["ffprobe"]:
        raise HTTPException(400, "请先安装 FFmpeg 与 FFprobe")
    project_id = db.uid()
    folder = directory(project_id)
    folder.mkdir(parents=True)
    limit = int(os.environ.get("MOVE_MAX_UPLOAD_MB", "2048")) * 1024 * 1024
    try:
        size = 0
        with (folder / "source").open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "视频超过上传大小限制（默认 2 GB）")
                target.write(chunk)
        metadata = await asyncio.to_thread(media.probe, folder / "source")
        if metadata["duration"] <= 0 or metadata["width"] <= 0:
            raise HTTPException(400, "请选择有效的视频文件")
        filename = (file.filename or "video").replace("\\", "/").split("/")[-1][:200]
        with db.connect() as con:
            con.execute(
                "INSERT INTO projects(id,name,source_name,metadata,created,updated) VALUES(?,?,?,?,?,?)",
                (
                    project_id,
                    filename.rsplit(".", 1)[0],
                    filename,
                    json.dumps(metadata),
                    db.now(),
                    db.now(),
                ),
            )
    except Exception as exc:
        shutil.rmtree(folder)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(400, "无法读取视频，请检查格式或 FFmpeg 安装") from exc
    finally:
        await file.close()
    enqueue(request, project_id, JobRequest(stage="prepare"))
    return get_project(project_id)


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    # Completion is published after project/cue updates. Read it first so a completed
    # job cannot be returned alongside project fields read before its final commit.
    job_values = db.jobs(project_id)
    value = require_project(project_id)
    folder = directory(project_id)
    saved_settings = db.settings()
    all_cues = db.cues(project_id)
    for cue in all_cues:
        cue["audio_ready"] = bool(
            cue["audio_file"]
            and cue["audio_hash"] == audio_hash(cue, saved_settings)
            and (folder / cue["audio_file"]).is_file()
        )
    signature = export_signature(saved_settings)
    return value | {
        "cues": all_cues,
        "jobs": job_values,
        "preview_ready": (folder / "preview.mp4").is_file(),
        "audio_ready": (folder / "audio.wav").is_file(),
        "dubbing_ready": (folder / "dubbing.wav").is_file(),
        "export_ready": (folder / "output.mp4").is_file(),
        "export_current": value["export_revision"] == value["subtitle_revision"]
        and value["export_signature"] == signature,
    }


@app.get("/api/projects/{project_id}/events")
async def events(project_id: str, request: Request):
    require_project(project_id)

    async def stream():
        previous = ""
        while not await request.is_disconnected():
            data = json.dumps(get_project(project_id), ensure_ascii=False)
            if data != previous:
                yield f"data: {data}\n\n"
                previous = data
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/projects/{project_id}/media/{kind}")
def get_media(project_id: str, kind: Literal["preview", "audio", "output", "dubbing"]):
    require_project(project_id)
    path = (
        directory(project_id)
        / {
            "preview": "preview.mp4",
            "audio": "audio.wav",
            "output": "output.mp4",
            "dubbing": "dubbing.wav",
        }[kind]
    )
    if not path.is_file():
        raise HTTPException(404, "文件尚未生成")
    return FileResponse(path, media_type="video/mp4" if path.suffix == ".mp4" else "audio/wav")


@app.get("/api/projects/{project_id}/cues/{cue_id}/audio")
def cue_audio(project_id: str, cue_id: str):
    require_project(project_id)
    cue = next((c for c in db.cues(project_id) if c["id"] == cue_id), None)
    if (
        not cue
        or not cue["audio_file"]
        or not (directory(project_id) / cue["audio_file"]).is_file()
    ):
        raise HTTPException(404, "该句尚未配音")
    path = directory(project_id) / cue["audio_file"]
    return FileResponse(path, media_type="audio/wav" if path.suffix == ".wav" else "audio/mpeg")


@app.get("/api/projects/{project_id}/waveform")
def waveform(project_id: str):
    require_project(project_id)
    path = directory(project_id) / "waveform.json"
    if not path.is_file():
        raise HTTPException(404, "波形尚未准备完成")
    return json.loads(path.read_text())


@app.get("/api/projects/{project_id}/subtitles")
def subtitles(project_id: str, mode: Literal["original", "translated", "bilingual"] = "bilingual"):
    require_project(project_id)
    return Response(
        media.srt(db.cues(project_id), mode),
        media_type="application/x-subrip",
        headers={"Content-Disposition": f'attachment; filename="move-{mode}.srt"'},
    )


@app.post("/api/projects/{project_id}/subtitles")
async def import_subtitles(
    project_id: str,
    kind: Literal["original", "translated"] = "original",
    file: UploadFile = File(...),
):
    project = require_project(project_id)
    idle(project_id)
    try:
        data = await file.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("字幕文件不得超过 5 MB")
        values = media.parse_srt(data.decode("utf-8-sig"))
        for cue in values:
            cue_times(cue["start"], cue["end"], project["metadata"]["duration"])
        # Check again after asynchronous upload, before any database mutation.
        idle(project_id)
        if kind == "original":
            with editing(project_id) as con:
                db.replace_cues(project_id, values, con)
        else:
            with editing(project_id) as con:
                existing = [
                    dict(row)
                    for row in con.execute(
                        "SELECT * FROM cues WHERE project_id=? ORDER BY start,position",
                        (project_id,),
                    )
                ]
                if len(existing) != len(values) or any(
                    abs(a["start"] - b["start"]) > 0.05 or abs(a["end"] - b["end"]) > 0.05
                    for a, b in zip(existing, values, strict=False)
                ):
                    raise ValueError("译文 SRT 的条数及时间轴必须与当前字幕一致")
                for before, after in zip(existing, values, strict=True):
                    con.execute(
                        "UPDATE cues SET translation=?,revision=revision+1,audio_hash=NULL,audio_duration=NULL,audio_file=NULL WHERE id=?",
                        (after["original"], before["id"]),
                    )
                db.changed(con, project_id)
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()
    return get_project(project_id)


class CueUpdate(BaseModel):
    revision: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    original: str = Field(min_length=1, max_length=10000)
    translation: str = Field(default="", max_length=10000)


@app.put("/api/projects/{project_id}/cues/{cue_id}")
def update_cue(project_id: str, cue_id: str, values: CueUpdate):
    project = require_project(project_id)
    idle(project_id)
    cue_times(values.start, values.end, project["metadata"]["duration"])
    if not values.original.strip():
        raise HTTPException(422, "原文不能为空")
    with editing(project_id) as con:
        before = con.execute(
            "SELECT * FROM cues WHERE id=? AND project_id=?", (cue_id, project_id)
        ).fetchone()
        if not before:
            raise HTTPException(404, "字幕不存在")
        if before["revision"] != values.revision:
            raise HTTPException(409, "字幕已更新，请刷新后重试")
        translation = values.translation.strip()
        if before["original"] != values.original.strip() and before["translation"] == translation:
            translation = ""
        invalidate = before["translation"] != translation
        con.execute(
            "UPDATE cues SET start=?,end=?,original=?,translation=?,revision=revision+1,"
            "audio_hash=?,audio_file=?,audio_duration=? WHERE id=?",
            (
                values.start,
                values.end,
                values.original.strip(),
                translation,
                None if invalidate else before["audio_hash"],
                None if invalidate else before["audio_file"],
                None if invalidate else before["audio_duration"],
                cue_id,
            ),
        )
        db.changed(con, project_id)
    return get_project(project_id)


class SplitRequest(BaseModel):
    revision: int
    at: float
    first_original: str = Field(min_length=1, max_length=10000)
    second_original: str = Field(min_length=1, max_length=10000)
    first_translation: str = Field(default="", max_length=10000)
    second_translation: str = Field(default="", max_length=10000)


@app.post("/api/projects/{project_id}/cues/{cue_id}/split")
def split(project_id: str, cue_id: str, values: SplitRequest):
    require_project(project_id)
    idle(project_id)
    if not values.first_original.strip() or not values.second_original.strip():
        raise HTTPException(422, "拆分后两条原文都不能为空")
    with editing(project_id) as con:
        cue = con.execute(
            "SELECT * FROM cues WHERE id=? AND project_id=?", (cue_id, project_id)
        ).fetchone()
        if not cue:
            raise HTTPException(404, "字幕不存在")
        if cue["revision"] != values.revision:
            raise HTTPException(409, "字幕已更改")
        if not cue["start"] < values.at < cue["end"]:
            raise HTTPException(422, "拆分时间必须在当前字幕范围内")
        con.execute("DELETE FROM cues WHERE id=?", (cue_id,))
        for i, start, end, original, translation in [
            (0, cue["start"], values.at, values.first_original, values.first_translation),
            (1, values.at, cue["end"], values.second_original, values.second_translation),
        ]:
            con.execute(
                "INSERT INTO cues(id,project_id,position,start,end,original,translation) VALUES(?,?,?,?,?,?,?)",
                (db.uid(), project_id, cue["position"] + i, start, end, original, translation),
            )
        db.changed(con, project_id)
    return get_project(project_id)


@app.post("/api/projects/{project_id}/cues/{cue_id}/merge")
def merge(project_id: str, cue_id: str, revision: int = Query(ge=0)):
    require_project(project_id)
    idle(project_id)
    cues = db.cues(project_id)
    index = next((i for i, c in enumerate(cues) if c["id"] == cue_id), -1)
    if index < 0 or index + 1 == len(cues):
        raise HTTPException(400, "没有下一条可合并字幕")
    first, second = cues[index : index + 2]
    if revision != first["revision"]:
        raise HTTPException(409, "字幕已更改")
    with editing(project_id) as con:
        second_current = con.execute(
            "SELECT revision FROM cues WHERE id=?", (second["id"],)
        ).fetchone()
        first_current = con.execute(
            "SELECT revision FROM cues WHERE id=?", (first["id"],)
        ).fetchone()
        if (
            not second_current
            or not first_current
            or second_current["revision"] != second["revision"]
            or first_current["revision"] != revision
        ):
            raise HTTPException(409, "字幕已更改，请刷新后合并")
        con.execute(
            "UPDATE cues SET end=?,original=?,translation=?,revision=revision+1,"
            "audio_hash=NULL,audio_file=NULL,audio_duration=NULL WHERE id=?",
            (
                max(first["end"], second["end"]),
                first["original"] + " " + second["original"],
                first["translation"] + second["translation"],
                first["id"],
            ),
        )
        con.execute("DELETE FROM cues WHERE id=?", (second["id"],))
        db.changed(con, project_id)
    return get_project(project_id)


class JobRequest(BaseModel):
    stage: Literal["prepare", "transcribe", "retranscribe", "translate", "dub", "export"]
    cue_ids: list[str] = Field(default_factory=list, max_length=30000)
    force: bool = False
    subtitle_mode: Literal["none", "original", "translated", "bilingual"] = "bilingual"
    use_dubbing: bool = True
    original_volume: float = Field(default=0, ge=0, le=0.5)


def enqueue(request: Request, project_id: str, values: JobRequest) -> dict:
    project = require_project(project_id)
    saved_settings = db.settings()
    if values.stage in {"transcribe", "retranscribe"} and not config.capabilities()["asr"]:
        raise HTTPException(400, config.capabilities()["asr_note"])
    provider = saved_settings["translation_provider"]
    if values.stage == "translate" and not providers.credential(provider):
        raise HTTPException(400, f"请在设置中配置 {provider} API Key")
    if values.stage == "dub":
        try:
            local_tts.require_ready(saved_settings)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    cues = db.cues(project_id)
    cue_ids = {c["id"] for c in cues}
    if not set(values.cue_ids) <= cue_ids:
        raise HTTPException(400, "选中字幕已不存在，请重新选择")
    if values.stage == "retranscribe" and len(values.cue_ids) != 1:
        raise HTTPException(400, "局部补识别一次选择一条字幕")
    if values.stage not in {"prepare", "transcribe"} and not cues:
        raise HTTPException(400, "请先识别或导入字幕")
    payload = values.model_dump() | {
        "settings": saved_settings,
        "revision": project["subtitle_revision"],
    }
    job_id = db.uid()
    with db.connect() as con:
        # Atomic check + enqueue protects against simultaneous double-clicks.
        con.execute("BEGIN IMMEDIATE")
        if con.execute(
            "SELECT id FROM jobs WHERE project_id=? AND status IN ('queued','running','cancelling')",
            (project_id,),
        ).fetchone():
            raise HTTPException(409, "当前项目已有任务正在处理")
        con.execute(
            "INSERT INTO jobs(id,project_id,stage,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)",
            (
                job_id,
                project_id,
                values.stage,
                "queued",
                json.dumps(payload, ensure_ascii=False),
                db.now(),
                db.now(),
            ),
        )
    request.app.state.runner.submit(job_id)
    return {"id": job_id, "status": "queued"}


@app.post("/api/projects/{project_id}/jobs", status_code=202)
def create_job(project_id: str, values: JobRequest, request: Request):
    return enqueue(request, project_id, values)


def require_job(project_id: str, job_id: str):
    require_project(project_id)
    with db.connect() as con:
        job = con.execute(
            "SELECT * FROM jobs WHERE id=? AND project_id=?", (job_id, project_id)
        ).fetchone()
    if not job:
        raise HTTPException(404, "任务不存在")
    return dict(job)


@app.post("/api/projects/{project_id}/jobs/{job_id}/cancel")
def cancel_job(project_id: str, job_id: str, request: Request):
    require_job(project_id, job_id)
    request.app.state.runner.cancel(job_id)
    return {"status": "ok"}


@app.post("/api/projects/{project_id}/jobs/{job_id}/retry", status_code=202)
def retry_job(project_id: str, job_id: str, request: Request):
    job = require_job(project_id, job_id)
    if job["status"] not in {"failed", "cancelled", "interrupted"}:
        raise HTTPException(400, "只有失败、取消或中断的任务可以重试")
    return enqueue(request, project_id, JobRequest(**json.loads(job["payload"])))


@app.get("/api/projects/{project_id}/jobs/{job_id}/candidate")
def candidate(project_id: str, job_id: str):
    job = require_job(project_id, job_id)
    if job["stage"] != "retranscribe" or job["status"] != "completed":
        raise HTTPException(400, "补识别尚未完成")
    return json.loads((directory(project_id) / f"asr-{job_id}.json").read_text(encoding="utf-8"))


@app.post("/api/projects/{project_id}/jobs/{job_id}/candidate")
def apply_candidate(project_id: str, job_id: str):
    job = require_job(project_id, job_id)
    idle(project_id)
    values = candidate(project_id, job_id)
    payload = json.loads(job["payload"])
    project = require_project(project_id)
    if project["subtitle_revision"] != payload["revision"]:
        raise HTTPException(409, "字幕已经修改，候选结果已过期；请重新补识别")
    selected_id = payload["cue_ids"][0]
    cues = db.cues(project_id)
    before = next(c for c in cues if c["id"] == selected_id)
    # Clamp contextual decoding to the selected interval; adjacent cues are preserved.
    values = [
        {**c, "start": max(before["start"], c["start"]), "end": min(before["end"], c["end"])}
        for c in values
    ]
    values = [c for c in values if c["end"] > c["start"]]
    if not values:
        raise HTTPException(400, "候选结果未覆盖选中字幕")
    with editing(project_id) as con:
        current = con.execute(
            "SELECT subtitle_revision FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if current["subtitle_revision"] != payload["revision"]:
            raise HTTPException(409, "字幕已更改，请重新补识别")
        con.execute("DELETE FROM cues WHERE id=?", (selected_id,))
        for i, cue in enumerate(values):
            con.execute(
                "INSERT INTO cues(id,project_id,position,start,end,original) VALUES(?,?,?,?,?,?)",
                (
                    db.uid(),
                    project_id,
                    before["position"] + i,
                    cue["start"],
                    cue["end"],
                    cue["original"],
                ),
            )
        db.changed(con, project_id)
    return get_project(project_id)


web = config.ROOT / "apps/web/dist"
if web.is_dir():
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
