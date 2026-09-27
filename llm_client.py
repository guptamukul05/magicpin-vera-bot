"""
llm_client.py — optional LLM call, stdlib-only (no SDK dependency).

Design decision (see README.md "Approach" for the full rationale):

  The composer (composer.py) is 100% rule/template based and produces a
  complete, spec-compliant, deterministic message on its own — with ZERO
  external dependencies and ZERO network calls. That is the bot's
  guaranteed baseline and is what runs by default.

  If VERA_USE_LLM=1 is set (and an API key is present for the selected
  VERA_LLM_PROVIDER), the composer additionally asks an LLM to *rewrite*
  the deterministic draft for more natural phrasing, while being
  instructed to preserve every fact already present and add nothing new
  (this keeps the "don't fabricate" constraint intact — see
  challenge-brief.md section 5, constraint #8). temperature=0 is used
  throughout so output stays deterministic given the same inputs, as
  required by the submission contract (challenge-brief.md section 7.1).

  If the LLM call fails for any reason (no key, network error, timeout,
  malformed response) we silently fall back to the deterministic draft.
  The bot must never 500 or blow the 30s budget because an LLM had a bad
  day — testing-brief.md section 5 gives us a firm per-call timeout.

Supported providers (set VERA_LLM_PROVIDER): "anthropic" (default model
claude-sonnet-4-6), "openai" (default gpt-4o-mini). Both are called via raw
HTTPS + urllib, exactly like judge_simulator.py does, so no pip install is
required to use this feature either.
"""

from __future__ import annotations

import json
import os
from urllib import request as urlrequest, error as urlerror

DEFAULT_TIMEOUT = 12  # seconds — must comfortably fit inside the 30s /v1/tick and /v1/reply budgets


def llm_enabled() -> bool:
    return os.environ.get("VERA_USE_LLM", "0") == "1"


def _provider() -> str:
    return os.environ.get("VERA_LLM_PROVIDER", "anthropic").lower()


def rewrite_with_llm(draft_body: str, system_prompt: str, facts_prompt: str) -> str | None:
    """Ask the configured LLM to polish `draft_body`. Returns the rewritten
    body, or None if the LLM is disabled / unavailable / fails for any reason
    (caller must fall back to `draft_body` in that case).
    """
    if not llm_enabled():
        return None

    provider = _provider()
    try:
        if provider == "anthropic":
            return _call_anthropic(system_prompt, facts_prompt, draft_body)
        if provider == "openai":
            return _call_openai(system_prompt, facts_prompt, draft_body)
    except Exception:
        # Never let an LLM hiccup break the response contract.
        return None
    return None


def _user_prompt(facts_prompt: str, draft_body: str) -> str:
    return (
        f"{facts_prompt}\n\n"
        f"DRAFT MESSAGE (already spec-compliant, correct facts, correct CTA shape):\n"
        f"\"\"\"\n{draft_body}\n\"\"\"\n\n"
        "Rewrite the draft to sound more natural and conversational, in the same "
        "language mix and voice. STRICT RULES: do not add any number, date, name, "
        "citation, or claim that is not already in the draft. Do not change what the "
        "call-to-action is asking for. Keep it roughly the same length or shorter. "
        "Output ONLY the rewritten message text, nothing else — no preamble, no quotes."
    )


def _call_anthropic(system_prompt: str, facts_prompt: str, draft_body: str) -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    model = os.environ.get("VERA_LLM_MODEL", "claude-sonnet-4-6")
    body = json.dumps({
        "model": model,
        "max_tokens": 400,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": _user_prompt(facts_prompt, draft_body)}],
    }).encode("utf-8")
    req = urlrequest.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
    )
    resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
    data = json.loads(resp.read().decode("utf-8"))
    text = data["content"][0]["text"].strip()
    return text or None


def _call_openai(system_prompt: str, facts_prompt: str, draft_body: str) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None
    model = os.environ.get("VERA_LLM_MODEL", "gpt-4o-mini")
    body = json.dumps({
        "model": model,
        "temperature": 0,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _user_prompt(facts_prompt, draft_body)},
        ],
    }).encode("utf-8")
    req = urlrequest.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    resp = urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT)
    data = json.loads(resp.read().decode("utf-8"))
    text = data["choices"][0]["message"]["content"].strip()
    return text or None
