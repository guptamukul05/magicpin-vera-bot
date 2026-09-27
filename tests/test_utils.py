import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import (
    classify_reply_kind,
    detect_script_mix,
    is_hostile,
    is_intent_transition,
    is_not_interested,
    is_verbatim_repeat_streak,
    looks_like_auto_reply_text,
    resolve_voice_language,
)


class TestAutoReply(unittest.TestCase):
    def test_signature_match(self):
        self.assertTrue(looks_like_auto_reply_text("Thank you for contacting us! Our team will respond shortly."))
        self.assertTrue(looks_like_auto_reply_text("Aapki jaankari ke liye bahut-bahut shukriya. Main aapki yeh sabhi baatein hamari team tak pahuncha deti hoon."))
        self.assertFalse(looks_like_auto_reply_text("Yes please, focus on whitening and aligners"))

    def test_verbatim_streak(self):
        history = ["Thank you!", "Thank you!"]
        self.assertTrue(is_verbatim_repeat_streak(history, "Thank you!", threshold=3))
        self.assertFalse(is_verbatim_repeat_streak(["Thank you!"], "Thank you!", threshold=3))

    def test_classify_auto_reply_on_first_turn(self):
        kind = classify_reply_kind([], "Thank you for contacting us! Our team will respond shortly.")
        self.assertEqual(kind, "auto_reply")


class TestIntent(unittest.TestCase):
    def test_positive(self):
        for msg in ["Ok lets do it. Whats next?", "Yes please, go ahead", "Sure, proceed", "Theek hai, karo", "haan bilkul"]:
            self.assertTrue(is_intent_transition(msg), msg)

    def test_negative(self):
        for msg in ["What does this cost?", "I'm not sure about this", "Can you explain more?"]:
            self.assertFalse(is_intent_transition(msg), msg)


class TestHostile(unittest.TestCase):
    def test_positive(self):
        self.assertTrue(is_hostile("Stop messaging me. This is useless spam."))

    def test_negative(self):
        self.assertFalse(is_hostile("This looks useful, thanks!"))


class TestNotInterested(unittest.TestCase):
    def test_positive(self):
        self.assertTrue(is_not_interested("Not interested, thanks"))
        self.assertTrue(is_not_interested("STOP"))

    def test_negative(self):
        self.assertFalse(is_not_interested("I'm very interested actually"))


class TestLanguage(unittest.TestCase):
    def test_devanagari(self):
        self.assertEqual(detect_script_mix("आपका स्वागत है"), "hi")

    def test_roman_hindi(self):
        self.assertEqual(detect_script_mix("aapka kya haal hai"), "hi-en")

    def test_english(self):
        self.assertEqual(detect_script_mix("What is the price?"), "en")

    def test_resolve_from_history_overrides_declared(self):
        lang = resolve_voice_language(["en"], ["theek hai bhai, kar do"])
        self.assertEqual(lang, "hi-en")

    def test_resolve_default(self):
        self.assertEqual(resolve_voice_language(["en"], None), "en")
        self.assertEqual(resolve_voice_language(["en", "hi"], None), "hi-en")


class TestClassifyPriority(unittest.TestCase):
    def test_hostile_wins_over_autoreply_text(self):
        # message is short and hostile; shouldn't be misread as anything else
        self.assertEqual(classify_reply_kind([], "Stop messaging me. This is useless spam."), "hostile")

    def test_off_topic(self):
        self.assertEqual(classify_reply_kind([], "can you also help me file my GST?"), "off_topic_question")


if __name__ == "__main__":
    unittest.main()
