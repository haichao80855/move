import json
import threading

import httpx
import pytest

from move_app import db, providers


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


def test_tts_contract_and_private_error_response(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "sensitive-test-key")

    def respond(request):
        assert request.url == "https://api.minimaxi.com/v1/t2a_v2"
        body = json.loads(request.content)
        assert body["voice_setting"]["voice_id"] == "male-qn-jingying"
        assert body["output_format"] == "hex" and not body["stream"]
        return httpx.Response(
            200, json={"base_resp": {"status_code": 0}, "data": {"audio": b"audio-test".hex()}}
        )

    transport(monkeypatch, respond)
    assert providers.synthesize("你好", db.DEFAULTS, threading.Event()) == b"audio-test"
    transport(
        monkeypatch, lambda request: httpx.Response(401, json={"error": "sensitive-test-key"})
    )
    with pytest.raises(RuntimeError) as failure:
        providers.synthesize("你好", db.DEFAULTS, threading.Event())
    assert "sensitive-test-key" not in str(failure.value)


def test_uncertain_paid_request_is_not_automatically_repeated(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "contract-only")
    requests = []

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("server may already have processed this", request=request)

    transport(monkeypatch, timeout)
    with pytest.raises(RuntimeError, match="手动重试"):
        providers.synthesize("你好", db.DEFAULTS, threading.Event())
    assert len(requests) == 1
