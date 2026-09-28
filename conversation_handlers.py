

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from reply_engine import build_reply
from state_store import ConversationState as _InternalConvState


@dataclass
class ConversationState:
    
    merchant: Optional[dict] = None
    category: Optional[dict] = None
    trigger: Optional[dict] = None
    customer: Optional[dict] = None

    conversation_id: str = "offline_conv_1"
    inbound_messages: List[str] = field(default_factory=list)
    sent_bodies: List[str] = field(default_factory=list)
    unanswered_nudges: int = 0
    ended: bool = False
    end_reason: Optional[str] = None

    # internal strike counters used by reply_engine (auto-reply / hostility)
    _auto_reply_strikes: int = 0
    _hostile_strikes: int = 0

    def _as_internal(self) -> _InternalConvState:
        conv = _InternalConvState(
            conversation_id=self.conversation_id,
            merchant_id=(self.merchant or {}).get("merchant_id", "unknown"),
            customer_id=(self.customer or {}).get("customer_id") if self.customer else None,
            trigger_id=(self.trigger or {}).get("id") if self.trigger else None,
        )
        conv.inbound_messages = list(self.inbound_messages)
        conv.sent_bodies = list(self.sent_bodies)
        conv.unanswered_nudges = self.unanswered_nudges
        conv.ended = self.ended
        setattr(conv, "_auto_reply_strikes", self._auto_reply_strikes)
        setattr(conv, "_hostile_strikes", self._hostile_strikes)
        return conv

    def _sync_from_internal(self, conv: _InternalConvState):
        self._auto_reply_strikes = getattr(conv, "_auto_reply_strikes", 0)
        self._hostile_strikes = getattr(conv, "_hostile_strikes", 0)


def respond(state: "ConversationState | Dict[str, Any]", merchant_message: str) -> dict:
   
    st = _coerce_state(state)
    internal = st._as_internal()

    def _lookup(_conv):
        return st.category, st.merchant, st.trigger, st.customer

    result = build_reply(internal, merchant_message, _lookup)

    # Persist history + strike counters back onto the caller's state object.
    st.inbound_messages.append(merchant_message)
    st._sync_from_internal(internal)
    if result.get("action") == "send" and result.get("body"):
        st.sent_bodies.append(result["body"])
    if result.get("action") == "end":
        st.ended = True
        st.end_reason = result.get("rationale")

    return result


def _coerce_state(state) -> ConversationState:
    if isinstance(state, ConversationState):
        return state
    if isinstance(state, dict):
        return ConversationState(**{k: v for k, v in state.items() if k in ConversationState.__dataclass_fields__})
    raise TypeError("state must be a ConversationState or dict")
