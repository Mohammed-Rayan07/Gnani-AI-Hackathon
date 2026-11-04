"""Provider quirks are absorbed, not fatal: JSON-mode rejection, thinking-model truncation, 429s."""

import asyncio
import json

import httpx

from chakravyuh.clients.llm import LLMClient
from chakravyuh.config import LLMRole


def _client(handler):
    c = LLMClient(LLMRole("judge", "http://llm.test/v1", "m", "k"))
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return c


def _ok(content, finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}]})


def test_drops_response_format_when_rejected():
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": "response_format json_object is not supported"})
        return _ok('{"ok": true}')

    c = _client(handler)
    assert asyncio.run(c.chat_json([{"role": "user", "content": "x"}])) == {"ok": True}
    assert seen == [True, False] and c._drop_json


def test_retries_with_bigger_budget_when_thinking_eats_tokens():
    budgets = []

    def handler(req):
        body = json.loads(req.content)
        budgets.append(body["max_tokens"])
        return _ok("", "length") if body["max_tokens"] < 1000 else _ok('{"ok": true}')

    assert asyncio.run(_client(handler).chat_json([{"role": "user", "content": "x"}], max_tokens=200)) == {"ok": True}
    assert budgets == [200, 800, 3200][: len(budgets)] and budgets[-1] >= 1000


def test_waits_out_rate_limit():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "0"}) if len(calls) < 3 else _ok('{"ok": true}')

    assert asyncio.run(_client(handler).chat_json([{"role": "user", "content": "x"}])) == {"ok": True}
    assert len(calls) == 3


def test_strips_reasoning_and_fences():
    assert asyncio.run(_client(lambda r: _ok('<think>hmm</think>```json\n{"ok": true}\n```')).chat_json(
        [{"role": "user", "content": "x"}])) == {"ok": True}
