"""
utils.py — small, dependency-free heuristics used across the bot.

Every function here is intentionally rule-based (no LLM call) so that:
  1. It's instant (<1ms), which matters because /v1/reply has a 30s budget
     and auto-reply / hostility / intent detection should never be the
     thing that eats that budget.
  2. It's deterministic and unit-testable in isolation.
  3. It works with zero external dependencies (stdlib only).

These heuristics back the "open challenges" called out in challenge-brief.md
section 12:
  1. Detect auto-replies vs real merchant replies.
  2. Handle intent transitions ("yes let's do it" -> action mode).
  4. Language detection per turn (hi / en / hi-en mix).
  5. Knowing when to stop (hostile, "not interested", 3 unanswered nudges).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    """Lowercase, strip accents/punctuation noise, collapse whitespace.
    Used for verbatim-repeat comparisons (auto-reply detection) so that
    trivial punctuation/whitespace differences don't defeat the check.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Auto-reply detection
# ---------------------------------------------------------------------------

# Canned WhatsApp Business auto-reply phrases we see in production Vera logs
# (per challenge-brief.md section 3, "Today's biggest pain points" #1, and
# Pattern B in section 9). Matching on these lets us flag on turn 1, instead
# of waiting for verbatim-repeat evidence to accumulate over 3 turns.
AUTO_REPLY_SIGNATURES = [
    "thank you for contacting",
    "thanks for contacting",
    "we will get back to you",
    "we'll get back to you",
    "our team will respond",
    "our team will get back",
    "currently unavailable",
    "will revert shortly",
    "hamari team tak pahuncha",
    "hum jald hi",
    "aapki jaankari ke liye",
    "automated assistant",
    "i am an automated",
    "this is an automated",
    "out of office",
    "busy right now",
]


def looks_like_auto_reply_text(message: str) -> bool:
    """Turn-1 heuristic: does this message's phrasing match a known canned
    WhatsApp Business auto-reply signature?"""
    norm = normalize(message)
    return any(sig in norm for sig in AUTO_REPLY_SIGNATURES)


def is_verbatim_repeat_streak(history: Iterable[str], new_message: str, threshold: int = 3) -> bool:
    """Production-Vera-style detection (hint in challenge-brief.md section 12):
    "same message verbatim 3+ times = auto-reply".
    `history` is the list of prior inbound messages *from this same role* in
    this conversation, oldest first. Returns True once the new message would
    make `threshold` verbatim (normalized) repeats in a row.
    """
    norm_new = normalize(new_message)
    if not norm_new:
        return False
    streak = 1  # counting the new message itself
    for prior in reversed(list(history)):
        if normalize(prior) == norm_new:
            streak += 1
        else:
            break
    return streak >= threshold


def classify_reply_kind(history: Iterable[str], new_message: str) -> str:
    """Returns one of: "auto_reply", "hostile", "not_interested",
    "intent_transition", "off_topic_question", "genuine".
    Order matters — hostile/not_interested take priority over auto-reply
    text-matching in case of overlap, since those need a graceful exit too.
    """
    if is_hostile(new_message):
        return "hostile"
    if is_not_interested(new_message):
        return "not_interested"
    if is_verbatim_repeat_streak(history, new_message) or looks_like_auto_reply_text(new_message):
        return "auto_reply"
    if is_intent_transition(new_message):
        return "intent_transition"
    if is_off_topic(new_message):
        return "off_topic_question"
    return "genuine"


# ---------------------------------------------------------------------------
# Intent transition detection (Pattern D anti-pattern in challenge-brief.md)
# ---------------------------------------------------------------------------

_INTENT_PATTERNS = [
    r"\blet'?s do (it|this)\b",
    r"\bgo ahead\b",
    r"\bok(ay)?[, ]+(let'?s|lets|go|do it|sounds good)\b",
    r"\byes[, ]*(please|do it|go ahead|send)\b",
    r"\bi want to (join|do this|proceed|sign up)\b",
    r"\bsign me up\b",
    r"\bcount me in\b",
    r"(?<!not )(?<!not sure )\bsure[, ]+(go ahead|do it|please)\b",
    r"\bproceed\b",
    r"\bconfirm(ed)?\b",
    r"\bplease (do|proceed|go ahead|update|check (and|&) update)\b",
    r"\bwhat'?s next\??\b",
    r"\bkaro\b",              # Hindi: "do it"
    r"\bkar do\b",
    r"\bchalega\b",           # Hindi: "works for me" / "fine"
    r"\btheek hai\b",         # Hindi: "okay"
    r"\bhaan\b",              # Hindi: "yes"
    r"\bji haan\b",
    r"\bkar dijiye\b",
    r"\bstart kar\w*\b",
    r"\bmujhe (join|karna hai)\b",
]
_INTENT_RE = re.compile("|".join(_INTENT_PATTERNS), re.IGNORECASE)

# A qualifying-question echo would be a false positive; explicit questions
# back *from the merchant* asking "how much / what is this" are NOT an
# intent transition — they're a genuine follow-up question.
_QUESTION_HEDGE_RE = re.compile(r"\?\s*$")


def is_intent_transition(message: str) -> bool:
    if not message:
        return False
    msg = message.strip()
    if _INTENT_RE.search(msg):
        return True
    return False


# ---------------------------------------------------------------------------
# Hostility / abuse detection
# ---------------------------------------------------------------------------

_HOSTILE_PATTERNS = [
    r"\bstop messaging\b",
    r"\bstop spamming\b",
    r"\bthis is spam\b",
    r"\buseless\b",
    r"\bidiot\b",
    r"\bnonsense\b",
    r"\bshut up\b",
    r"\bfraud\b",
    r"\bscam\b",
    r"\bharass",
    r"\breport(ing)? you\b",
    r"\bgo away\b",
    r"\bblock(ed|ing)? you\b",
    r"\bmadarchod\b",
    r"\bbhenchod\b",
    r"\bbakwas\b",
    r"\bbewakoof\b",
]
_HOSTILE_RE = re.compile("|".join(_HOSTILE_PATTERNS), re.IGNORECASE)


def is_hostile(message: str) -> bool:
    return bool(message) and bool(_HOSTILE_RE.search(message))


# ---------------------------------------------------------------------------
# "Not interested" / opt-out detection
# ---------------------------------------------------------------------------

_NOT_INTERESTED_PATTERNS = [
    r"\bnot interested\b",
    r"\bno thanks?\b",
    r"^\s*stop\s*$",
    r"\bunsubscribe\b",
    r"\bdon'?t (message|contact|text) me\b",
    r"\bnahi chahiye\b",
    r"\bnahi karna\b",
    r"\bmana kar diya\b",
    r"\bleave me alone\b",
    r"\bplease stop\b",
]
_NOT_INTERESTED_RE = re.compile("|".join(_NOT_INTERESTED_PATTERNS), re.IGNORECASE)


def is_not_interested(message: str) -> bool:
    return bool(message) and bool(_NOT_INTERESTED_RE.search(message))


# ---------------------------------------------------------------------------
# Off-topic detection (Phase-4 "hostile / off-topic" replay scenario)
# ---------------------------------------------------------------------------

_OFF_TOPIC_PATTERNS = [
    r"\bgst\b",
    r"\bincome tax\b",
    r"\bloan\b",
    r"\binsurance\b",
    r"\bvisa\b",
    r"\bpassport\b",
    r"\blegal advice\b",
    r"\bpolitic",
]
_OFF_TOPIC_RE = re.compile("|".join(_OFF_TOPIC_PATTERNS), re.IGNORECASE)


def is_off_topic(message: str) -> bool:
    return bool(message) and bool(_OFF_TOPIC_RE.search(message))


# ---------------------------------------------------------------------------
# Language detection / matching
# ---------------------------------------------------------------------------

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_ROMAN_HINDI_WORDS = {
    "hai", "hain", "nahi", "nahin", "kya", "aap", "aapka", "aapke", "kar",
    "karo", "kijiye", "chahiye", "theek", "haan", "bhi", "abhi", "mera",
    "meri", "mujhe", "sakte", "dena", "batao", "acha", "accha", "bahut",
    "shukriya", "dhanyawad", "ji", "wala", "wali", "kaise", "kab", "kyun",
}


def detect_script_mix(text: str) -> str:
    """Rough detector for whether inbound text is 'en', 'hi' (Devanagari),
    or 'hi-en' (roman Hindi mixed with English)."""
    if not text:
        return "en"
    if _DEVANAGARI_RE.search(text):
        return "hi"
    words = set(re.findall(r"[a-zA-Z']+", text.lower()))
    hindi_hits = words & _ROMAN_HINDI_WORDS
    if hindi_hits and len(hindi_hits) >= 1 and len(words) > 0:
        return "hi-en"
    return "en"


def resolve_voice_language(
    merchant_languages: Optional[list],
    conversation_history_texts: Optional[list] = None,
) -> str:
    """Decide which language register to compose in.

    Priority (per challenge-brief.md section 5, constraint #7 — "match the
    merchant's language", and open-challenge #4 — "language may switch
    mid-conversation"):
      1. If the merchant's *most recent* message in this conversation shows
         a clear script/mix, honor that (people switch languages mid-thread).
      2. Else fall back to their declared `identity.languages` preference.
      3. Default to English.
    """
    if conversation_history_texts:
        for text in reversed(conversation_history_texts):
            detected = detect_script_mix(text)
            if detected != "en":
                return detected
        # last message was plain english -> respect that turn
        if conversation_history_texts:
            return detect_script_mix(conversation_history_texts[-1])

    langs = merchant_languages or []
    if "hi" in langs and "en" in langs:
        return "hi-en"
    if langs == ["hi"]:
        return "hi"
    return "en"


# ---------------------------------------------------------------------------
# Misc small helpers
# ---------------------------------------------------------------------------

def pct(value) -> str:
    """0.18 -> '18%', -0.05 -> '-5%'. None/non-numeric -> '' (never the string 'None')."""
    if value is None or isinstance(value, bool):
        return ""
    try:
        return f"{float(value) * 100:+.0f}%".replace("+-", "-")
    except Exception:
        return ""


def pct_abs(value) -> str:
    """abs(0.18) -> '18%'. None/non-numeric -> '' (never the string 'None')."""
    if value is None or isinstance(value, bool):
        return ""
    try:
        return f"{abs(float(value)) * 100:.0f}%"
    except Exception:
        return ""


_HONORIFICS = {"mr", "mr.", "mrs", "mrs.", "ms", "ms.", "dr", "dr.", "shri", "smt", "smt."}


def first_name(full_or_first: Optional[str]) -> str:
    """Extract a usable first/display name. Keeps an honorific attached to
    the next token (e.g. "Mr. Sharma" -> "Mr. Sharma", not "Mr.") since a
    bare honorific reads as a copy bug, not a name."""
    if not full_or_first:
        return "there"
    parts = full_or_first.strip().split()
    if not parts:
        return "there"
    if parts[0].lower().rstrip(".") in {h.rstrip(".") for h in _HONORIFICS} and len(parts) > 1:
        return f"{parts[0]} {parts[1]}"
    return parts[0]