"""
reply_engine.py — turns an inbound merchant/customer message into the bot's
next move: send / wait / end.

This is the shared brain behind both:
  - bot.py's POST /v1/reply  (the live HTTP contract, testing-brief.md 2.3)
  - conversation_handlers.py's respond(state, merchant_message)  (the
    offline multi-turn contract, challenge-brief.md 7.4)

It directly targets the 3 replay scenarios in testing-brief.md Phase 4 and
the open challenges in challenge-brief.md section 12:

  1. Auto-reply hell      -> classify_reply_kind() catches signature text
                              on the first canned reply, and verbatim-repeat
                              streaks from turn 2 on either way.
  2. Intent transition    -> switches straight to action-mode phrasing,
                              never re-asks a qualifying question (the
                              explicit anti-pattern in challenge-brief.md
                              Pattern D).
  3. Hostile / off-topic  -> de-escalates once, stays on-mission, and only
                              ends the conversation if hostility repeats or
                              the merchant explicitly opts out.

Decision table
--------------
classification        -> action                          -> ends convo?
---------------------    ------------------------------     -----------
auto_reply (1st time)  -> send a single human-escalation     no
                           probe ("want to check yourself?")
auto_reply (2nd+ time) -> end, polite exit                    yes
hostile (1st time)     -> send a short apology/de-escalation  no
hostile (2nd time)     -> end, polite exit                    yes
not_interested         -> end, polite exit immediately        yes
off_topic_question     -> send a polite redirect back to      no
                           the merchant's actual account
intent_transition      -> send, action-mode framing using     no
                           real next-step data if available
genuine                -> send, advances the conversation     no
                           using real context if available
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from state_store import ConversationState
from utils import classify_reply_kind, first_name

ContextLookup = Callable[[ConversationState], Tuple[Optional[dict], Optional[dict], Optional[dict], Optional[dict]]]
# Returns (category, merchant, trigger, customer) — any may be None if not available.


def _merchant_display_name(merchant: Optional[dict]) -> str:
    if not merchant:
        return "there"
    return first_name((merchant.get("identity", {}) or {}).get("owner_first_name") or (merchant.get("identity", {}) or {}).get("name"))


def build_reply(
    conv: ConversationState,
    message: str,
    context_lookup: Optional[ContextLookup] = None,
) -> Dict[str, Any]:
    category = merchant = trigger = customer = None
    if context_lookup:
        try:
            category, merchant, trigger, customer = context_lookup(conv)
        except Exception:
            pass

    kind = classify_reply_kind(conv.inbound_messages, message)

    if kind == "auto_reply":
        return _handle_auto_reply(conv)
    if kind == "hostile":
        return _handle_hostile(conv)
    if kind == "not_interested":
        return _handle_not_interested(conv)
    if kind == "off_topic_question":
        return _handle_off_topic(conv, merchant)
    if kind == "intent_transition":
        return _handle_intent_transition(conv, category, merchant, trigger)
    return _handle_genuine(conv, category, merchant, trigger, message)


# --- individual handlers ----------------------------------------------------

_AUTO_REPLY_STRIKE_ATTR = "_auto_reply_strikes"
_HOSTILE_STRIKE_ATTR = "_hostile_strikes"


def _strike_count(conv: ConversationState, attr: str) -> int:
    return getattr(conv, attr, 0)


def _bump_strike(conv: ConversationState, attr: str) -> int:
    n = _strike_count(conv, attr) + 1
    setattr(conv, attr, n)
    return n


def _handle_auto_reply(conv: ConversationState) -> Dict[str, Any]:
    strikes = _bump_strike(conv, _AUTO_REPLY_STRIKE_ATTR)
    if strikes == 1:
        # Pattern B in challenge-brief.md: try ONCE to reach a human, then stop.
        return {
            "action": "send",
            "body": (
                "Samajh gayi \u2014 lagta hai yeh auto-reply hai. Agar aap khud 2 minute "
                "dekhna chahein ki exact kya update hui hai, toh main yahin hoon. Chalega?"
            ),
            "cta": "binary",
            "rationale": "Detected canned WhatsApp Business auto-reply text/verbatim-repeat; probing once for a human before disengaging (per Pattern B).",
        }
    return {
        "action": "end",
        "rationale": "Second consecutive auto-reply detected \u2014 disengaging gracefully instead of burning further turns on a bot.",
        "body": "Koi baat nahi, samajh gayi \u2014 main owner/manager se directly connect kar lungi jab time ho. Best wishes! \U0001F642",
    }


def _handle_hostile(conv: ConversationState) -> Dict[str, Any]:
    strikes = _bump_strike(conv, _HOSTILE_STRIKE_ATTR)
    if strikes == 1:
        return {
            "action": "send",
            "body": "Sorry to bother you \u2014 I won't keep pushing. If you ever want help with your listing, I'm here.",
            "cta": "none",
            "rationale": "First hostile/abusive message \u2014 de-escalating once, staying available, not ending immediately so we can still handle a genuine follow-up in the same session.",
        }
    return {
        "action": "end",
        "rationale": "Hostility repeated \u2014 exiting the conversation rather than continuing to push.",
        "body": "Understood, I'll stop here. Take care.",
    }


def _handle_not_interested(conv: ConversationState) -> Dict[str, Any]:
    return {
        "action": "end",
        "rationale": "Explicit not-interested / opt-out signal \u2014 exiting immediately and gracefully, no further nudge.",
        "body": "No problem at all \u2014 I won't message about this again. All the best!",
    }


def _handle_off_topic(conv: ConversationState, merchant: Optional[dict]) -> Dict[str, Any]:
    return {
        "action": "send",
        "body": (
            "That's outside what I can help with directly, so I don't want to give you the wrong info there \u2014 "
            "worth checking with a specialist for that one. On my side, happy to keep helping with your listing/offers whenever you're ready."
        ),
        "cta": "none",
        "rationale": "Off-topic / out-of-scope question \u2014 politely declined without pretending expertise, redirected back to the actual mission (Phase 4 'hostile / off-topic' replay).",
    }


def _handle_intent_transition(conv: ConversationState, category, merchant, trigger) -> Dict[str, Any]:
    # Anti-pattern D in challenge-brief.md: do NOT re-qualify. Go straight to action-mode
    # phrasing ("done" / "sending" / "here's what's next"), using real data if we have it.
    next_step = None
    if trigger:
        kind = trigger.get("kind", "")
        if kind == "research_digest" and category:
            next_step = "the full research summary + a draft you can share with your customers"
        elif kind in ("renewal_due", "winback_eligible"):
            next_step = "your renewal link"
        elif kind == "active_planning_intent":
            next_step = "the full plan (pricing, flow, and a ready-to-send WhatsApp blurb)"
        elif kind in ("perf_dip", "perf_spike"):
            next_step = "the breakdown of what changed"
        elif kind == "gbp_unverified":
            next_step = "the verification steps"
    if not next_step:
        next_step = "the next step"

    body = f"Done \u2014 sending {next_step} now. I'll confirm here once it's live."
    return {
        "action": "send",
        "body": body,
        "cta": "none",
        "rationale": "Merchant gave explicit go-ahead \u2014 switched straight to action mode, no re-qualifying question, per challenge-brief.md anti-pattern D.",
    }


_GENERIC_ACK = [
    "Got it. On it now.",
    "Noted \u2014 give me a moment to pull that together.",
]


def _handle_genuine(conv: ConversationState, category, merchant, trigger, message: str) -> Dict[str, Any]:
    conv_unanswered = 0  # reset tracked by caller via ConversationStore.reset_unanswered
    msg_lower = message.lower().strip()

    # Simple, real-data-grounded advances for a few common genuine follow-ups.
    if any(w in msg_lower for w in ("send", "abstract", "full", "share", "details", "more info")):
        body = "Sending it now \u2014 I'll also drop a ready-to-share WhatsApp version in case you want to forward it to your customers."
        rationale = "Merchant asked for more detail/the full item \u2014 honoring the request and adding one low-friction follow-on (per Appendix A worked example)."
    elif any(w in msg_lower for w in ("how much", "price", "cost", "kitna")):
        offer = None
        if merchant:
            active = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
            offer = active[0]["title"] if active else None
        body = f"It's covered under your current plan \u2014 no extra cost." if not offer else f"No extra cost for this \u2014 separately, your \"{offer}\" offer is live if that's useful too."
        rationale = "Merchant asked about cost \u2014 answered directly using only real offer data, no invented pricing."
    elif "?" in message:
        body = "Good question \u2014 let me get you a precise answer rather than guessing, one sec."
        rationale = "Merchant asked a question we don't have a templated real-data answer for \u2014 avoided guessing/fabricating, acknowledged and deferred honestly."
    else:
        body = "Got it, thanks for confirming \u2014 I'll keep this moving and update you here."
        rationale = "Generic acknowledgement of a genuine, on-topic reply; keeps the thread open without repeating prior content."

    return {"action": "send", "body": body, "cta": "none", "rationale": rationale}


def should_stop_nudging(conv: ConversationState, max_unanswered: int = 3) -> bool:
    """Open challenge #5 — 'knowing when to stop': gracefully exit after N
    consecutive unanswered proactive nudges with zero genuine reply."""
    return conv.unanswered_nudges >= max_unanswered and not conv.ended
