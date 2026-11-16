"""Run a language model on an episode through any OpenAI-compatible Chat Completions API
(OpenAI, OpenRouter, Groq, Gemini's OpenAI endpoint, vLLM, Ollama, ...). Standard library only."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .env import Env, tool_schemas

NUDGE = "Continue working with the tools. Call end_day when today's work is done."


class LLMError(RuntimeError):
    pass


def _post(url: str, payload: Dict[str, Any], api_key: Optional[str], retries: int = 4) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    delay = 2.0
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise LLMError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise LLMError(str(exc)) from exc
    raise LLMError("unreachable")


def run_llm(model: str, level: str, seed: int, base_url: str = "https://api.openai.com/v1",
            api_key: Optional[str] = None, max_turns: int = 1500, temperature: Optional[float] = None,
            log: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    env = Env(level, seed)
    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                               "parameters": t["input_schema"]}} for t in tool_schemas()]
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": env.brief()},
        {"role": "user", "content": "Your first day starts now."},
    ]
    url = base_url.rstrip("/") + "/chat/completions"
    idle = 0
    for _ in range(max_turns):
        if env.done:
            break
        payload: Dict[str, Any] = {"model": model, "messages": messages, "tools": tools}
        if temperature is not None:
            payload["temperature"] = temperature
        data = _post(url, payload, api_key)
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         **({"tool_calls": calls} if calls else {})})
        if not calls:
            idle += 1
            if idle >= 3:  # the model stopped using tools: close the day for it
                env.step({"tool": "end_day", "args": {}})
                idle = 0
            messages.append({"role": "user", "content": NUDGE})
            continue
        idle = 0
        for call in calls:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
                obs = {"ok": False, "error": "arguments were not valid JSON"}
            else:
                obs, _, _, _ = env.step({"tool": fn.get("name"), "args": args})
            if log is not None:
                log.append({"day": env.day, "tool": fn.get("name"), "args": args, "obs": obs})
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(obs)})
            if env.done:
                break
    if not env.done:
        env._finish()
    result = dict(env.result)
    result["model"] = model
    return result


def api_key_from_env(name: Optional[str]) -> Optional[str]:
    if name:
        return os.environ.get(name)
    for candidate in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY"):
        if os.environ.get(candidate):
            return os.environ[candidate]
    return None
