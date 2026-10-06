import array
import json
import subprocess
import threading
import wave

import pytest
from conftest import settled

from move_app import config, db, media, providers
from move_app.pipeline import Runner, audio_hash, directory

ORIGINAL = "1\n00:00:00,500 --> 00:00:01,400\nHello world.\n\n2\n00:00:02,000 --> 00:00:03,500\nWelcome to Move.\n"
TRANSLATED = ORIGINAL.replace("Hello world.", "你好，世界。").replace(
    "Welcome to Move.", "欢迎使用 Move。"
)


def test_source_edit_invalidates_only_its_translation(client, project):
    value = imported(client, project)
    cue = value["cues"][0]
    response = client.put(
        f"/api/projects/{value['id']}/cues/{cue['id']}", json=cue | {"original": "Hello new world."}
    )
    assert response.status_code == 200
    assert response.json()["cues"][0]["translation"] == ""
    assert response.json()["cues"][1]["translation"] == "欢迎使用 Move。"


def test_mac_keychain_contract_never_returns_or_persists_raw_key(client, monkeypatch):
    vault = {}
    monkeypatch.setattr(providers.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        providers.keyring, "set_password", lambda service, name, value: vault.update({name: value})
    )
    monkeypatch.setattr(providers.keyring, "get_password", lambda service, name: vault.get(name))
    key = "private-keychain-contract-only"
    response = client.put("/api/settings", json={"keys": {"deepseek": key}})
    assert response.status_code == 200
    assert response.json()["credentials"]["deepseek"] is True
    assert key not in response.text
    assert key.encode() not in (config.DATA / "move.sqlite").read_bytes()
    assert vault["deepseek"] == key


def imported(client, project):
    project_id = project["id"]
    response = client.post(
        f"/api/projects/{project_id}/subtitles", files={"file": ("source.srt", ORIGINAL.encode())}
    )
    assert response.status_code == 200
    response = client.post(
        f"/api/projects/{project_id}/subtitles?kind=translated",
        files={"file": ("zh.srt", TRANSLATED.encode())},
    )
    assert response.status_code == 200
    return response.json()


def test_real_video_dubbing_export_cache_and_invalidation(client, project, tmp_path, monkeypatch):
    project = imported(client, project)
    project_id = project["id"]
    audio_path = tmp_path / "speech.mp3"
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
            "0.55",
            str(audio_path),
        ],
        check=True,
    )
    calls = []
    monkeypatch.setenv("MINIMAX_API_KEY", "contract-test-only")

    def synthesis(text, settings, cancel):
        calls.append(text)
        return audio_path.read_bytes()

    monkeypatch.setattr(providers, "synthesize", synthesis)
    assert client.post(f"/api/projects/{project_id}/jobs", json={"stage": "dub"}).status_code == 202
    project = settled(client, project_id)
    assert project["jobs"][0]["status"] == "completed", project["jobs"]
    assert all(c["audio_ready"] for c in project["cues"])
    assert len(calls) == 2
    client.post(f"/api/projects/{project_id}/jobs", json={"stage": "dub"})
    assert settled(client, project_id)["jobs"][0]["status"] == "completed"
    assert len(calls) == 2, "Cached audio should not make paid calls again"
    client.post(
        f"/api/projects/{project_id}/jobs", json={"stage": "export", "subtitle_mode": "bilingual"}
    )
    result = settled(client, project_id)
    assert result["jobs"][0]["status"] == "completed", result["jobs"]
    assert result["export_ready"] and result["export_current"]
    path = directory(project_id)
    assert abs(media.probe(path / "output.mp4")["duration"] - 4) < 0.2
    with wave.open(str(path / "dubbing.wav"), "rb") as audio:
        assert audio.getnframes() == 96000
        samples = array.array("h", audio.readframes(audio.getnframes()))
    assert max(abs(x) for x in samples[:10000]) == 0, "Leading silence must be preserved"
    assert max(abs(x) for x in samples[12500:18000]) > 0, (
        "First cue must be audible at its timestamp"
    )
    assert max(abs(x) for x in samples[35000:45000]) == 0, "Inter-cue silence must be preserved"
    response = client.get(
        f"/api/projects/{project_id}/media/output", headers={"Range": "bytes=0-99"}
    )
    assert response.status_code == 206 and len(response.content) == 100
    cue = result["cues"][0]
    response = client.put(
        f"/api/projects/{project_id}/cues/{cue['id']}", json=cue | {"translation": "改写第一句。"}
    )
    assert response.status_code == 200
    assert not response.json()["cues"][0]["audio_ready"]
    assert response.json()["cues"][1]["audio_ready"]
    assert not response.json()["export_current"]
    client.post(f"/api/projects/{project_id}/jobs", json={"stage": "dub"})
    assert settled(client, project_id)["jobs"][0]["status"] == "completed"
    assert len(calls) == 3, "Only the changed cue should be regenerated"


def test_subtitle_edit_conflict_split_merge_and_export_without_credentials(client, project):
    project = imported(client, project)
    project_id, cue = project["id"], project["cues"][0]
    route = f"/api/projects/{project_id}/cues/{cue['id']}"
    assert client.put(route, json=cue | {"end": 1.5}).status_code == 200
    assert client.put(route, json=cue | {"end": 1.6}).status_code == 409
    updated = client.get(f"/api/projects/{project_id}").json()["cues"][0]
    response = client.post(
        route + "/split",
        json={
            "revision": updated["revision"],
            "at": 1.0,
            "first_original": "Hello",
            "second_original": "world.",
            "first_translation": "你好",
            "second_translation": "世界。",
        },
    )
    assert response.status_code == 200
    cues = response.json()["cues"]
    assert len(cues) == 3 and cues[0]["end"] == cues[1]["start"] == 1
    response = client.post(f"/api/projects/{project_id}/cues/{cues[0]['id']}/merge?revision=0")
    assert response.status_code == 200 and len(response.json()["cues"]) == 2
    client.post(
        f"/api/projects/{project_id}/jobs",
        json={"stage": "export", "use_dubbing": False, "subtitle_mode": "translated"},
    )
    result = settled(client, project_id)
    assert result["jobs"][0]["status"] == "completed", result["jobs"]
    text = client.get(f"/api/projects/{project_id}/subtitles?mode=bilingual").text
    assert "你好世界。" in text and "Hello world." in text
    assert len(media.parse_srt(text)) == 2


def test_import_validation_and_credentials_are_not_leaked(client, project):
    project = imported(client, project)
    project_id = project["id"]
    before = project["cues"]
    response = client.post(
        f"/api/projects/{project_id}/subtitles?kind=translated",
        files={"file": ("wrong.srt", TRANSLATED.replace("00:00:00,500", "00:00:00,800").encode())},
    )
    assert response.status_code == 400
    assert client.get(f"/api/projects/{project_id}").json()["cues"] == before
    assert (
        client.post(f"/api/projects/{project_id}/jobs", json={"stage": "translate"}).status_code
        == 400
    )
    assert client.post(f"/api/projects/{project_id}/jobs", json={"stage": "dub"}).status_code == 400
    response = client.put("/api/settings", json={"keys": {"minimax": "never-write-this-secret"}})
    assert response.status_code == 400  # Linux deliberately does not store raw keys on disk.
    assert b"never-write-this-secret" not in (config.DATA / "move.sqlite").read_bytes()
    assert (
        client.put("/api/settings", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403


def test_export_rejects_overlong_dub_and_keeps_previous_output(client, project):
    project = imported(client, project)
    project_id = project["id"]
    folder = directory(project_id)
    (folder / "output.mp4").write_bytes(b"previous export")
    settings = db.settings()
    with db.connect() as con:
        for cue in project["cues"]:
            con.execute(
                "UPDATE cues SET audio_hash=?,audio_file='segments/test.mp3',audio_duration=4 WHERE id=?",
                (audio_hash(cue, settings), cue["id"]),
            )
    client.post(f"/api/projects/{project_id}/jobs", json={"stage": "export"})
    result = settled(client, project_id)
    assert result["jobs"][0]["status"] == "failed"
    assert "配音过长" in result["jobs"][0]["error"]
    assert (folder / "output.mp4").read_bytes() == b"previous export"


def test_job_cancel_and_restart_recovery(client, project, monkeypatch):
    project = imported(client, project)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    started = threading.Event()

    def translate(cues, context, settings, cancel):
        started.set()
        assert cancel.wait(5)
        media.check_cancel(cancel)

    monkeypatch.setattr(providers, "translate", translate)
    route = f"/api/projects/{project['id']}"
    response = client.post(route + "/jobs", json={"stage": "translate", "force": True})
    assert started.wait(5)
    cue = project["cues"][0]
    assert client.put(route + f"/cues/{cue['id']}", json=cue).status_code == 409
    assert client.post(route + "/jobs", json={"stage": "translate"}).status_code == 409
    client.post(route + f"/jobs/{response.json()['id']}/cancel")
    result = settled(client, project["id"])
    assert result["jobs"][0]["status"] == "cancelled"
    assert result["cues"][0]["translation"] == cue["translation"]
    with db.connect() as con:
        con.execute(
            "INSERT INTO jobs(id,project_id,stage,status,payload,created,updated) VALUES(?,?,?,?,?,?,?)",
            (
                "interrupted-test",
                project["id"],
                "dub",
                "running",
                json.dumps({}),
                db.now(),
                db.now(),
            ),
        )
    runner = Runner()
    runner.start()
    runner.close()
    assert db.jobs(project["id"])[0]["status"] == "interrupted"


@pytest.mark.parametrize(
    "text", ["", "1\n00:61:00,000 --> 00:61:01,000\nBad", "1\n00:00:02,000 --> 00:00:01,000\nBad"]
)
def test_srt_rejects_invalid_timing(text):
    with pytest.raises(ValueError):
        media.parse_srt(text)
