

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    trigger_id: Optional[str] = None
    scope: str = "merchant"  # "merchant" | "customer"
    turn_number: int = 0
    sent_bodies: List[str] = field(default_factory=list)         # everything WE sent (anti-repeat)
    inbound_messages: List[str] = field(default_factory=list)    # everything THEY sent, oldest first
    unanswered_nudges: int = 0                                   # consecutive vera sends with no genuine reply
    ended: bool = False
    end_reason: Optional[str] = None
    first_touch_sent: bool = False                                # whether the 24h-session opener went out
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    detected_language: Optional[str] = None


class ContextStore:
    def __init__(self):
        self._lock = threading.RLock()
        # (scope, context_id) -> {"version": int, "payload": dict}
        self._store: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def put(self, scope: str, context_id: str, version: int, payload: dict) -> Tuple[bool, dict]:
        """Returns (accepted, info). Idempotent + monotonic per testing-brief 2.1."""
        with self._lock:
            key = (scope, context_id)
            current = self._store.get(key)
            if current is not None and version <= current["version"]:
                return False, {"reason": "stale_version", "current_version": current["version"]}
            self._store[key] = {"version": version, "payload": payload, "updated_at": time.time()}
            return True, {"current_version": version}

    def get(self, scope: str, context_id: str) -> Optional[dict]:
        with self._lock:
            entry = self._store.get((scope, context_id))
            return entry["payload"] if entry else None

    def get_version(self, scope: str, context_id: str) -> Optional[int]:
        with self._lock:
            entry = self._store.get((scope, context_id))
            return entry["version"] if entry else None

    def all_ids(self, scope: str) -> List[str]:
        with self._lock:
            return [cid for (s, cid) in self._store.keys() if s == scope]

    def counts(self) -> Dict[str, int]:
        with self._lock:
            out: Dict[str, int] = {}
            for (scope, _cid) in self._store.keys():
                out[scope] = out.get(scope, 0) + 1
            for scope in ("category", "merchant", "customer", "trigger"):
                out.setdefault(scope, 0)
            return out

    def clear(self):
        with self._lock:
            self._store.clear()

    # Convenience accessors used by the composer -----------------------------------
    def category_for_merchant(self, merchant_id: str) -> Optional[dict]:
        merchant = self.get("merchant", merchant_id)
        if not merchant:
            return None
        slug = merchant.get("category_slug")
        return self.get("category", slug) if slug else None


class ConversationStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._conversations: Dict[str, ConversationState] = {}

    def get_or_create(
        self,
        conversation_id: str,
        merchant_id: str,
        customer_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
    ) -> ConversationState:
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv is None:
                conv = ConversationState(
                    conversation_id=conversation_id,
                    merchant_id=merchant_id,
                    customer_id=customer_id,
                    trigger_id=trigger_id,
                    scope="customer" if customer_id else "merchant",
                )
                self._conversations[conversation_id] = conv
            return conv

    def get(self, conversation_id: str) -> Optional[ConversationState]:
        with self._lock:
            return self._conversations.get(conversation_id)

    def record_sent(self, conversation_id: str, body: str):
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.sent_bodies.append(body)
                conv.unanswered_nudges += 1
                conv.first_touch_sent = True
                conv.updated_at = time.time()

    def record_inbound(self, conversation_id: str, message: str):
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.inbound_messages.append(message)
                conv.updated_at = time.time()

    def reset_unanswered(self, conversation_id: str):
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.unanswered_nudges = 0

    def end(self, conversation_id: str, reason: str):
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if conv:
                conv.ended = True
                conv.end_reason = reason

    def has_sent_body(self, conversation_id: str, body: str) -> bool:
        """Anti-repetition check (testing-brief section 10 penalty)."""
        with self._lock:
            conv = self._conversations.get(conversation_id)
            if not conv:
                return False
            norm_target = _norm(body)
            return any(_norm(b) == norm_target for b in conv.sent_bodies)

    def all_conversation_ids_for_merchant(self, merchant_id: str) -> List[str]:
        with self._lock:
            return [cid for cid, c in self._conversations.items() if c.merchant_id == merchant_id]

    def clear(self):
        with self._lock:
            self._conversations.clear()


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())
