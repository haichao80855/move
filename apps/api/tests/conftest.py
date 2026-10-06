import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from move_app import config
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
