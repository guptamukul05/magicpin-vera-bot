import json
import os
import subprocess
import sys
import time
import unittest
from urllib import request as urlrequest, error as urlerror

ROOT = os.path.join(os.path.dirname(__file__), "..")
PORT = int(os.environ.get("TEST_BOT_PORT", "8099"))
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None, timeout=10):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urlrequest.Request(f"{BASE}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        resp = urlrequest.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class BotServerTestCase(unittest.TestCase):
    proc = None

    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env["PORT"] = str(PORT)
        env["VERA_USE_LLM"] = "0"
        cls.proc = subprocess.Popen(
            [sys.executable, "bot.py"], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        for _ in range(50):
            try:
                status, _ = call("GET", "/v1/healthz", timeout=2)
                if status == 200:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("bot.py server did not become healthy in time")

    @classmethod
    def tearDownClass(cls):
        if cls.proc:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

    def setUp(self):
        call("POST", "/v1/teardown", {})

    # -- basic contract -------------------------------------------------

    def test_healthz(self):
        status, data = call("GET", "/v1/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertIn("contexts_loaded", data)

    def test_metadata(self):
        status, data = call("GET", "/v1/metadata")
        self.assertEqual(status, 200)
        for key in ("team_name", "model", "approach", "version"):
            self.assertIn(key, data)

    def test_context_push_idempotent_and_versioned(self):
        category = _sample_category()
        status, data = call("POST", "/v1/context", {
            "scope": "category", "context_id": "dentists", "version": 1,
            "payload": category, "delivered_at": "2026-04-26T10:00:00Z",
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["accepted"])

        # re-posting same version -> stale, rejected with 409
        status, data = call("POST", "/v1/context", {
            "scope": "category", "context_id": "dentists", "version": 1,
            "payload": category, "delivered_at": "2026-04-26T10:00:00Z",
        })
        self.assertEqual(status, 409)
        self.assertFalse(data["accepted"])
        self.assertEqual(data["reason"], "stale_version")

        # higher version -> accepted
        status, data = call("POST", "/v1/context", {
            "scope": "category", "context_id": "dentists", "version": 2,
            "payload": category, "delivered_at": "2026-04-26T11:00:00Z",
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["accepted"])

    def test_context_malformed_400(self):
        status, data = call("POST", "/v1/context", {"scope": "not_a_scope"})
        self.assertEqual(status, 400)
        self.assertFalse(data["accepted"])

    # -- tick -> proactive send ------------------------------------------

    def test_tick_composes_and_returns_action(self):
        _push_full_scenario()
        status, data = call("POST", "/v1/tick", {
            "now": "2026-04-26T10:30:00Z",
            "available_triggers": ["trg_research"],
        })
        self.assertEqual(status, 200)
        actions = data["actions"]
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertTrue(action["body"].strip())
        self.assertIn(action["cta"], ("binary", "open_ended", "none"))
        self.assertEqual(action["send_as"], "vera")
        self.assertIn("JIDA", action["body"])  # cited source should carry through

    def test_tick_empty_when_no_triggers(self):
        status, data = call("POST", "/v1/tick", {"now": "2026-04-26T10:30:00Z", "available_triggers": []})
        self.assertEqual(status, 200)
        self.assertEqual(data["actions"], [])

    def test_tick_does_not_resend_same_suppression_key(self):
        _push_full_scenario()
        call("POST", "/v1/tick", {"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_research"]})
        status, data = call("POST", "/v1/tick", {"now": "2026-04-26T10:35:00Z", "available_triggers": ["trg_research"]})
        self.assertEqual(data["actions"], [])  # already sent, deduped by suppression_key

    # -- reply scenarios (Phase 4 replay style) --------------------------

    def test_auto_reply_hell(self):
        _push_full_scenario()
        call("POST", "/v1/tick", {"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_research"]})
        auto_msg = "Thank you for contacting us! Our team will respond shortly."
        results = []
        for i in range(1, 5):
            status, data = call("POST", "/v1/reply", {
                "conversation_id": "conv_m_001_drmeera_dentist_delhi_trg_research",
                "merchant_id": "m_001_drmeera_dentist_delhi", "customer_id": None,
                "from_role": "merchant", "message": auto_msg,
                "received_at": "2026-04-26T10:45:00Z", "turn_number": i + 1,
            })
            self.assertEqual(status, 200)
            results.append(data["action"])
            if data["action"] == "end":
                break
        self.assertIn("end", results, f"bot never ended on repeated auto-reply: {results}")
        self.assertLessEqual(results.index("end"), 1, "should end within first 2 turns of canned auto-reply text")

    def test_intent_transition_switches_to_action(self):
        _push_full_scenario()
        call("POST", "/v1/tick", {"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_research"]})
        status, data = call("POST", "/v1/reply", {
            "conversation_id": "conv_m_001_drmeera_dentist_delhi_trg_research",
            "merchant_id": "m_001_drmeera_dentist_delhi", "customer_id": None,
            "from_role": "merchant", "message": "Ok lets do it. Whats next?",
            "received_at": "2026-04-26T10:45:00Z", "turn_number": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["action"], "send")
        body_lower = data["body"].lower()
        for qualifying in ("would you", "do you", "can you tell", "how about"):
            self.assertNotIn(qualifying, body_lower)
        self.assertTrue(any(w in body_lower for w in ("done", "sending", "draft", "here", "confirm", "proceed", "next")))

    def test_hostile_does_not_blow_up_and_deescalates(self):
        _push_full_scenario()
        call("POST", "/v1/tick", {"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_research"]})
        status, data = call("POST", "/v1/reply", {
            "conversation_id": "conv_m_001_drmeera_dentist_delhi_trg_research",
            "merchant_id": "m_001_drmeera_dentist_delhi", "customer_id": None,
            "from_role": "merchant", "message": "Stop messaging me. This is useless spam.",
            "received_at": "2026-04-26T10:45:00Z", "turn_number": 2,
        })
        self.assertEqual(status, 200)
        self.assertIn(data["action"], ("send", "end"))
        if data["action"] == "send":
            self.assertTrue(any(w in data["body"].lower() for w in ("sorry", "apolog", "won't", "understood")))

    def test_not_interested_ends_gracefully(self):
        _push_full_scenario()
        call("POST", "/v1/tick", {"now": "2026-04-26T10:30:00Z", "available_triggers": ["trg_research"]})
        status, data = call("POST", "/v1/reply", {
            "conversation_id": "conv_m_001_drmeera_dentist_delhi_trg_research",
            "merchant_id": "m_001_drmeera_dentist_delhi", "customer_id": None,
            "from_role": "merchant", "message": "Not interested, please stop.",
            "received_at": "2026-04-26T10:45:00Z", "turn_number": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["action"], "end")

    def test_malformed_reply_handled_safely(self):
        status, data = call("POST", "/v1/reply", {"conversation_id": "", "message": ""})
        self.assertEqual(status, 200)
        self.assertIn("action", data)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _sample_category():
    with open(os.path.join(ROOT, "dataset", "categories", "dentists.json"), encoding="utf-8") as f:
        return json.load(f)


def _sample_merchant():
    with open(os.path.join(ROOT, "dataset", "merchants_seed.json"), encoding="utf-8") as f:
        data = json.load(f)
    return next(m for m in data["merchants"] if m["merchant_id"] == "m_001_drmeera_dentist_delhi")


def _push_full_scenario():
    call("POST", "/v1/context", {
        "scope": "category", "context_id": "dentists", "version": 1,
        "payload": _sample_category(), "delivered_at": "2026-04-26T09:00:00Z",
    })
    call("POST", "/v1/context", {
        "scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1,
        "payload": _sample_merchant(), "delivered_at": "2026-04-26T09:00:00Z",
    })
    trigger = {
        "id": "trg_research", "scope": "merchant", "kind": "research_digest",
        "source": "external", "merchant_id": "m_001_drmeera_dentist_delhi", "customer_id": None,
        "payload": {"category": "dentists", "top_item_id": "d_2026W17_jida_fluoride"},
        "urgency": 2, "suppression_key": "research:dentists:2026-W17",
        "expires_at": "2026-05-03T00:00:00Z",
    }
    call("POST", "/v1/context", {
        "scope": "trigger", "context_id": "trg_research", "version": 1,
        "payload": trigger, "delivered_at": "2026-04-26T09:00:00Z",
    })


if __name__ == "__main__":
    unittest.main()
