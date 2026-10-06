import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from move_app import config, db, local_tts
from move_app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path / "data")
    for key in ["DEEPSEEK_API_KEY", "QWEN_API_KEY", "MINIMAX_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    with TestClient(app) as connection:
        yield connection


@pytest.fixture(scope="session")
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=12",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=300:sample_rate=24000",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    return path


def settled(client, project_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get(f"/api/projects/{project_id}").json()
        if not any(j["status"] in {"running", "queued", "cancelling"} for j in result["jobs"]):
            return result
        time.sleep(0.05)
    raise AssertionError("Worker did not complete")


@pytest.fixture
def project(client, video):
    with video.open("rb") as source:
        response = client.post("/api/projects", files={"file": ("示例.mp4", source, "video/mp4")})
    assert response.status_code == 201, response.text
    value = settled(client, response.json()["id"])
    assert value["jobs"][0]["status"] == "completed", value["jobs"]
    assert value["preview_ready"] and value["audio_ready"]
    peaks = client.get(f"/api/projects/{value['id']}/waveform").json()
    assert 0 < len(peaks["peaks"]) <= 1600
    assert abs(peaks["duration"] - 4) < 0.2
    assert 0 < max(peaks["peaks"]) <= 1
    return value


@pytest.fixture
def reference_audio(tmp_path):
    path = tmp_path / "reference.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=800:sample_rate=24000",
            "-t",
            "4",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def local_runtime(client, monkeypatch, reference_audio):
    original = config.capabilities
    monkeypatch.setattr(config, "capabilities", lambda: original() | {"apple_silicon": True})
    monkeypatch.setattr(config, "TTS_PYTHON", config.ROOT / "apps/api/.venv/bin/python")
    folder = local_tts.model_dir()
    folder.mkdir(parents=True)
    (folder / "config.json").write_text("{}")
    (folder / "model.safetensors").write_bytes(b"contract-only-no-mlx")
    (folder / "speech_tokenizer").mkdir()
    (folder / "speech_tokenizer/config.json").write_text("{}")
    (folder / "speech_tokenizer/model.safetensors").write_bytes(b"contract-only-no-mlx")
    (folder / "ready.json").write_text(
        json.dumps(
            {
                "model": config.TTS_MODEL,
                "revision": "test-revision",
                "worker": local_tts.WORKER_VERSION,
            }
        )
    )
    with reference_audio.open("rb") as source:
        response = client.post(
            "/api/tts/references",
            files={"file": ("reference.wav", source)},
            data={"transcript": "这是参考音频的文字。"},
        )
    assert response.status_code == 201, response.text
    value = response.json()
    db.save_settings({"reference_id": value["id"]})
    return value
