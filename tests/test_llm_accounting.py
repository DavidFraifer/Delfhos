import cortex._engine.tools.websearch as websearch_module
from cortex._engine.utils.llm_utils import normalize_llm_result


def test_normalize_llm_result_keeps_image_count_and_total_fallback():
    response, token_info = normalize_llm_result(
        (
            "ok",
            {
                "input_tokens": 12,
                "output_tokens": 8,
                "image_count": 2,
            },
        )
    )

    assert response == "ok"
    assert token_info["input_tokens"] == 12
    assert token_info["output_tokens"] == 8
    assert token_info["total_tokens"] == 20
    assert token_info["image_count"] == 2
    assert token_info["llm_calls"] == 1


def test_web_search_returns_complete_token_payload(monkeypatch):
    async def _fake_llm_web_search(query: str, task_id: str, model: str, agent_id: str = None):
        return "summary", {
            "input_tokens": 10,
            "output_tokens": 15,
            "image_count": 1,
            "llm_calls": 1,
        }

    monkeypatch.setattr(websearch_module, "_llm_web_search", _fake_llm_web_search)

    import asyncio

    summary, token_info = asyncio.run(
        websearch_module.web_search(query="latest ai news", task_id="t1", model="gemini-3.1-flash-lite-preview")
    )

    assert summary == "summary"
    assert token_info["input_tokens"] == 10
    assert token_info["output_tokens"] == 15
    assert token_info["total_tokens"] == 25
    assert token_info["tokens_used"] == 25
    assert token_info["image_count"] == 1
    assert token_info["llm_calls"] == 1