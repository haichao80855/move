import json
import os
import threading
import time
import wave
from pathlib import Path

from move_app import config, db, local_tts, media
from move_app.pipeline import audio_hash, export_signature


def settled_task(client):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        value = client.get("/api/tts/status").json()["task"]
        if value and value["status"] not in {"queued", "running", "cancelling"}:
            return value
        time.sleep(0.05)
    raise AssertionError("TTS task did not settle")


def test_reference_is_normalized_private_and_editable(client, local_runtime):
    value = local_runtime
    response = client.get(value["audio_url"], headers={"Range": "bytes=0-43"})
    assert response.status_code == 206 and response.content[:4] == b"RIFF"
    assert response.headers["content-type"] == "audio/wav"
    with wave.open(str(local_tts.reference_path(value["id"])), "rb") as audio:
        assert audio.getnchannels() == 1 and audio.getframerate() == 24000
    settings = db.settings()
    before = audio_hash({"translation": "你好"}, settings)
    old_export = export_signature(settings)
    response = client.put(
        f"/api/tts/references/{value['id']}", json={"transcript": "修正后的参考文字"}
    )
    assert response.status_code == 200
    assert audio_hash({"translation": "你好"}, settings) != before
    assert export_signature(settings) != old_export
    assert client.get("/api/tts/references").json()[0]["transcript"] == "修正后的参考文字"
    assert client.get("/api/tts/references/not-a-reference/audio").status_code == 404


def test_reference_rejects_invalid_media_and_blank_transcript(client):
    assert (
        client.post(
            "/api/tts/references",
            files={"file": ("bad.wav", b"not-audio")},
            data={"transcript": "原话"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/tts/references",
            files={"file": ("bad.wav", b"not-audio")},
            data={"transcript": " "},
        ).status_code
        == 422
    )
    assert not client.get("/api/tts/references").json()
    assert not list((config.DATA / "references").glob("*"))


def test_linux_reports_unavailable_instead_of_claiming_model_success(client):
    value = client.get("/api/tts/status").json()
    assert not value["supported"] and not value["model_ready"]
    assert "Apple Silicon" in value["note"]
    assert client.post("/api/tts/prepare").status_code == 400


def test_missing_speech_encoder_clears_ready_state(client, local_runtime):
    (local_tts.model_dir() / "speech_tokenizer/model.safetensors").unlink()
    assert not client.get("/api/tts/status").json()["model_ready"]


def test_preview_uses_current_values_and_reuses_raw_audio_for_speed(
    client, local_runtime, monkeypatch
):
    calls = []

    def worker(mode, values, cancel, progress):
        assert mode == "generate" and local_tts.MLX_LOCK.locked()
        assert values["reference_text"] == local_runtime["transcript"]
        assert Path(values["reference_audio"]).is_file()
        calls.append(values)
        for item in values["items"]:
            media.ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=500:sample_rate=24000",
                    "-t",
                    "1",
                    item["path"],
                ],
                cancel,
            )

    monkeypatch.setattr(local_tts, "worker", worker)
    settings = db.settings()
    urls = []
    for speed in [1, 1.5]:
        result = client.post(
            "/api/tts/preview",
            json={"reference_id": local_runtime["id"], "text": "当前测试文字", "speed": speed},
        )
        assert result.status_code == 202
        task = settled_task(client)
        assert task["status"] == "completed", task
        response = client.get(task["audio_url"])
        assert response.status_code == 200 and response.content[:4] == b"RIFF"
        urls.append(task["audio_url"])
    assert len(calls) == 1 and calls[0]["items"][0]["text"] == "当前测试文字"
    path = config.DATA / "tts-previews" / (urls[-1].rsplit("/", 1)[1] + ".wav")
    assert abs(media.probe(path)["duration"] - 1 / 1.5) < 0.05
    assert db.settings() == settings, "Testing must not save draft settings"
    assert client.get("/api/tts/previews/not-an-id").status_code == 404


def test_preview_can_be_cancelled_while_waiting_for_asr_resource(
    client, local_runtime, monkeypatch
):
    def unexpected(*args):
        raise AssertionError("A cancelled waiting job must not load a second model")

    monkeypatch.setattr(local_tts, "worker", unexpected)
    with local_tts.exclusive(threading.Event()):
        response = client.post(
            "/api/tts/preview", json={"reference_id": local_runtime["id"], "text": "等待取消"}
        )
        assert response.status_code == 202
        assert (
            client.post(
                "/api/tts/preview", json={"reference_id": local_runtime["id"], "text": "第二次"}
            ).status_code
            == 409
        )
        assert (
            client.put(
                f"/api/tts/references/{local_runtime['id']}", json={"transcript": "修改"}
            ).status_code
            == 409
        )
        assert client.post("/api/tts/cancel").status_code == 200
        assert settled_task(client)["status"] == "cancelled"


def test_cancel_terminates_isolated_worker_and_uses_offline_local_inputs(
    client, local_runtime, monkeypatch, tmp_path
):
    worker = tmp_path / "workers/tts/synthesize.py"
    worker.parent.mkdir(parents=True)
    pid_file = tmp_path / "worker-pid"
    worker.write_text(
        "import json, os, sys, time\nfrom pathlib import Path\n"
        "assert sys.argv[1] == 'generate'\n"
        "data = json.loads(Path(sys.argv[2]).read_text())\n"
        "assert os.environ['HF_HUB_OFFLINE'] == '1'\n"
        "assert os.environ['TRANSFORMERS_OFFLINE'] == '1'\n"
        "assert Path(data['reference_audio']).is_file()\n"
        "assert data['reference_text'] == '这是参考音频的文字。'\n"
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(120)\n"
    )
    monkeypatch.setattr(config, "ROOT", tmp_path)
    assert (
        client.post(
            "/api/tts/preview",
            json={
                "reference_id": local_runtime["id"],
                "text": "取消正在执行的进程",
            },
        ).status_code
        == 202
    )
    deadline = time.monotonic() + 5
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pid_file.exists(), "Worker did not receive a valid offline manifest"
    pid = int(pid_file.read_text())
    assert client.post("/api/tts/cancel").status_code == 200
    assert settled_task(client)["status"] == "cancelled"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("Cancelled worker must release the model process")


def test_preparation_requires_verified_receipt_and_surfaces_failure(
    client, local_runtime, monkeypatch
):
    def fail(mode, values, cancel, progress):
        assert mode == "prepare"
        raise RuntimeError("模型下载失败")

    monkeypatch.setattr(local_tts, "worker", fail)
    assert client.post("/api/tts/prepare").status_code == 202
    task = settled_task(client)
    assert task["status"] == "failed" and task["error"] == "模型下载失败"


def test_legacy_settings_and_queued_cloud_job_migrate_without_losing_media(client, project):
    previous = config.DATA / "historical.mp3"
    previous.write_bytes(b"keep-existing-media")
    db.save_settings({"tts_model": "speech-02-hd", "voice_id": "old-voice"})
    with db.connect() as con:
        con.execute("DELETE FROM settings WHERE key='tts_provider'")
        con.execute(
            "INSERT INTO jobs(id,project_id,stage,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)",
            (
                "legacy",
                project["id"],
                "dub",
                "queued",
                json.dumps({"settings": {"tts_model": "speech-02-hd"}}),
                db.now(),
                db.now(),
            ),
        )
    db.initialize()
    assert db.settings()["tts_model"] == config.TTS_MODEL
    assert "voice_id" not in db.settings() and previous.read_bytes() == b"keep-existing-media"
    assert db.project(project["id"]) is not None
    assert next(j for j in db.jobs(project["id"]) if j["id"] == "legacy")["status"] == "interrupted"
