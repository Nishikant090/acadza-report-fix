"""Tiny Claude client with a response cache (stdlib only, no SDK needed).

- With ANTHROPIC_API_KEY set: calls the Messages API and writes the response to the cache.
- Without it: replays engine/cache/<stage>.json. This is how the committed results.json
  and the live console were produced (see PROMPTS.md, "How results.json was produced").
"""
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
MODELS = {"solver": "claude-sonnet-5-5", "triage": "claude-opus-5-5"}
MAX_TOKENS = {"solver": 900, "triage": 2500}


def _hash(*parts):
    return hashlib.sha256("\n\x00".join(parts).encode()).hexdigest()[:16]


def _load(stage):
    p = CACHE_DIR / f"{stage}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save(stage, data):
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{stage}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("model returned no JSON object")
    return json.loads(m.group(0))


def call(stage, key, system, user, stats):
    """Return parsed JSON for (stage, key). Cached by key; prompt hash recorded for drift checks."""
    cache = _load(stage)
    h = _hash(MODELS[stage], system, user)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    hit = cache.get(key)
    if hit and (not api_key or hit.get("_prompt_hash") == h):
        stats["cache_hits"] += 1
        return {k: v for k, v in hit.items() if not k.startswith("_")}
    if not api_key:
        raise RuntimeError(f"No cached {stage} output for {key} and ANTHROPIC_API_KEY is not set")
    body = {
        "model": MODELS[stage],
        "max_tokens": MAX_TOKENS[stage],
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    stats["api_calls"] += 1
    u = resp.get("usage", {})
    stats["input_tokens"] += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    stats["output_tokens"] += u.get("output_tokens", 0)
    out = _extract_json("".join(b.get("text", "") for b in resp["content"]))
    cache[key] = {**out, "_prompt_hash": h, "_model": MODELS[stage]}
    _save(stage, cache)
    return out
