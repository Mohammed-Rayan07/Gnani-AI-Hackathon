"""OpenAI-compatible chat client used for all three LLM roles.

One client covers every Evon tier from the plan:
  Tier 1  Evon v3.3 on vLLM          base_url=http://<gpu-box>:8000/v1
          extra body {"chat_template_kwargs": {"enable_thinking": false}}
  Tier 2  Evon GGUF on llama.cpp/Ollama  base_url=http://localhost:11434/v1
  Tier 3  any hosted OpenAI-compatible LLM
Every result carries the model name so reports attribute work honestly.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from ..cache import DiskCache, key
from ..config import LLMRole
from ._http import GnaniAPIError, request_with_retry

log = logging.getLogger("chakravyuh.llm")
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    """Parse the first JSON object in a reply (tolerates reasoning traces and code fences)."""
    text = THINK_RE.sub("", text).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    raise LLMError(f"No JSON object in model output: {text[:300]!r}")


class LLMClient:
    def __init__(self, role: LLMRole, cache: DiskCache | None = None):
        self.role = role
        self.cache = cache
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0))
        self._drop_json = False
        self._drop_seed = False
        self.usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}

    @property
    def label(self) -> str:
        return self.role.label

    async def chat(self, messages: list[dict], *, temperature: float = 0.0, max_tokens: int = 800,
                   json_mode: bool = False, use_cache: bool = True, seed: int | None = None) -> str:
        if not self.role.configured:
            raise LLMError(f"{self.role.role.upper()}_LLM_BASE_URL / _MODEL not set")
        body = {"model": self.role.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode and self.role.json_mode:
            body["response_format"] = {"type": "json_object"}
        if seed is not None:
            body["seed"] = seed
        body.update(self.role.extra_body)
        k = key("llm", self.role.base_url, body)
        cacheable = temperature == 0.0 or seed is not None   # seeded sampling replays from cache
        if use_cache and self.cache and cacheable:
            hit = self.cache.get_json(k)
            if hit is not None:
                return hit["content"]
        headers = {"Content-Type": "application/json"}
        if self.role.api_key:
            headers["Authorization"] = f"Bearer {self.role.api_key}"
        content = await self._post_adaptive(body, headers)
        if use_cache and self.cache and cacheable:
            self.cache.put_json(k, {"content": content})
        return content

    async def _post_adaptive(self, body: dict, headers: dict) -> str:
        """POST, adapting to provider quirks instead of failing the run:
        - a 400 mentioning response_format / seed: drop that field for this client and retry;
        - empty content with finish_reason=length (thinking models spend the budget on
          reasoning): retry once with a 4x token budget."""
        body = dict(body)
        for _ in range(4):
            if self._drop_json:
                body.pop("response_format", None)
            if self._drop_seed:
                body.pop("seed", None)
            try:
                r = await request_with_retry(self._http, "POST", f"{self.role.base_url}/chat/completions",
                                             what=f"LLM[{self.role.role}]", headers=headers, json=body)
            except GnaniAPIError as e:
                msg = e.body.lower()
                if e.status == 400 and "response_format" in body and ("response_format" in msg or "json" in msg) and not self._drop_json:
                    log.warning("%s rejected response_format; retrying without it (set %s_LLM_JSON_MODE=false to skip)",
                                self.role.model, self.role.role.upper())
                    self._drop_json = True
                    continue
                if e.status == 400 and "seed" in body and "seed" in msg and not self._drop_seed:
                    self._drop_seed = True
                    continue
                raise
            data = r.json()
            u = data.get("usage") or {}
            self.usage["requests"] += 1
            self.usage["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
            self.usage["completion_tokens"] += int(u.get("completion_tokens") or 0)
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
            if choice.get("finish_reason") == "length" and body.get("max_tokens", 0) < 6000:
                # Thinking models (e.g. Gemini 3.x Flash) spend the budget on hidden reasoning and
                # return empty OR cut-off content; a truncated reply must never reach the caller.
                body["max_tokens"] = body.get("max_tokens", 800) * 4
                continue
            return content
        raise LLMError(f"{self.role.model}: no usable reply after adapting the request")

    async def chat_json(self, messages: list[dict], *, temperature: float = 0.0, max_tokens: int = 800,
                        retries: int = 2, seed: int | None = None) -> dict:
        last = None
        for attempt in range(retries + 1):
            out = await self.chat(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True,
                                  use_cache=attempt == 0, seed=seed)
            try:
                return extract_json(out)
            except LLMError as e:
                last = e
                messages = messages + [{"role": "assistant", "content": out},
                                       {"role": "user", "content": "That was not a single valid JSON object. Reply with ONLY the JSON object."}]
        raise last  # type: ignore[misc]

    async def aclose(self) -> None:
        await self._http.aclose()
