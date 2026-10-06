import json
import threading

import httpx
import pytest

from move_app import config, db, providers


def transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(
        providers, "client", lambda: original(transport=httpx.MockTransport(handler))
    )


def test_translation_contract_preserves_ids_and_uses_context(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "contract-only")
    cues = [{"id": "one", "original": "Hello"}, {"id": "two", "original": "World"}]

    def respond(request):
        assert request.url == "https://api.deepseek.com/chat/completions"
        body = json.loads(request.content)
        payload = json.loads(body["messages"][1]["content"])
        assert payload["context"][0]["translation"] == "前文"
        assert [c["id"] for c in payload["subtitles"]] == ["one", "two"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "translations": [
                                        {"id": "two", "text": "世界"},
                                        {"id": "one", "text": "你好"},
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    transport(monkeypatch, respond)
    assert providers.translate(
        cues, [{"original": "Earlier", "translation": "前文"}], db.DEFAULTS, threading.Event()
    ) == {"two": "世界", "one": "你好"}


def test_translation_rejects_missing_or_duplicate_ids(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "contract-only")
    transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"translations":[{"id":"one","text":"中文"},{"id":"one","text":"重复"}]}'
                        }
                    }
                ]
            },
        ),
    )
    with pytest.raises(RuntimeError, match="缺条"):
        providers.translate(
            [{"id": "one", "original": "Hello"}],
            [],
            db.DEFAULTS | {"translation_provider": "qwen"},
            threading.Event(),
        )


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "credentials"),
        (403, "credentials"),
        (402, "balance"),
        (404, "model"),
        (400, "model"),
        (422, "model"),
        (429, "rate_limit"),
        (503, "service"),
    ],
)
def test_deepseek_distinguishes_failures_without_retries_or_secret_echo(
    client, monkeypatch, status, code
):
    requests = []
    key = "transient-private-key"

    def respond(request):
        requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {key}"
        return httpx.Response(status, json={"error": key})

    transport(monkeypatch, respond)
    response = client.post("/api/services/deepseek/test", json={"model": "bad-model", "key": key})
    assert response.status_code == 200
    assert response.json()["code"] == code and not response.json()["ok"]
    assert response.json()["elapsed_ms"] >= 0
    assert len(requests) == 1 and key not in response.text
    assert key.encode() not in (config.DATA / "move.sqlite").read_bytes()


def test_deepseek_uses_unsaved_model_and_key_without_changing_settings(client, monkeypatch):
    before = client.get("/api/settings").json()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "existing-key")
    seen = []

    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == "deepseek-reasoner"
        assert body["max_tokens"] == 16 and body["stream"] is False
        seen.append(request.headers["Authorization"])
        return httpx.Response(200, json={"choices": [{"message": {"reasoning_content": "OK"}}]})

    transport(monkeypatch, respond)
    for key, expected in [("unsaved-key", "Bearer unsaved-key"), ("", "Bearer existing-key")]:
        result = client.post(
            "/api/services/deepseek/test", json={"model": "deepseek-reasoner", "key": key}
        ).json()
        assert result["ok"] and result["model"] == "deepseek-reasoner"
        assert seen[-1] == expected
    assert db.settings()["deepseek_model"] == before["deepseek_model"]
    assert b"unsaved-key" not in (config.DATA / "move.sqlite").read_bytes()


@pytest.mark.parametrize(
    "error,code", [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "network")]
)
def test_deepseek_timeout_and_network_errors_are_private(client, monkeypatch, error, code):
    requests = []

    def fail(request):
        requests.append(request)
        raise error("do-not-echo-private-key", request=request)

    transport(monkeypatch, fail)
    result = client.post(
        "/api/services/deepseek/test",
        json={"model": "deepseek-chat", "key": "do-not-echo-private-key"},
    )
    assert result.json()["code"] == code and len(requests) == 1
    assert "do-not-echo-private-key" not in result.text


def test_deepseek_missing_key_and_invalid_inputs_do_not_leak(client):
    assert (
        client.post("/api/services/deepseek/test", json={"model": "deepseek-chat"}).json()["code"]
        == "credentials"
    )
    key = "private" * 200
    result = client.post("/api/services/deepseek/test", json={"model": "deepseek-chat", "key": key})
    assert result.status_code == 422 and key not in result.text
    for key in ["不是有效的密钥", "key\nwith-newline"]:
        response = client.post(
            "/api/services/deepseek/test", json={"model": "deepseek-chat", "key": key}
        )
        assert response.json()["code"] == "credentials" and key not in response.text
