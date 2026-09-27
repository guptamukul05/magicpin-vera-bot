import glob
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from composer import compose_message
from bot import compose


ROOT = os.path.join(os.path.dirname(__file__), "..")
EXPANDED = os.path.join(ROOT, "expanded")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@unittest.skipUnless(os.path.isdir(EXPANDED), "run `python3 dataset/generate_dataset.py --seed-dir dataset --out expanded` first")
class TestComposerAgainstFullDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.categories = {_load(f)["slug"]: _load(f) for f in glob.glob(os.path.join(EXPANDED, "categories", "*.json"))}
        cls.merchants = {_load(f)["merchant_id"]: _load(f) for f in glob.glob(os.path.join(EXPANDED, "merchants", "*.json"))}
        cls.customers = {_load(f)["customer_id"]: _load(f) for f in glob.glob(os.path.join(EXPANDED, "customers", "*.json"))}
        cls.triggers = {_load(f)["id"]: _load(f) for f in glob.glob(os.path.join(EXPANDED, "triggers", "*.json"))}

    def test_every_trigger_composes_without_error(self):
        composed = 0
        for trg in self.triggers.values():
            merchant = self.merchants.get(trg.get("merchant_id"))
            if not merchant:
                continue
            category = self.categories.get(merchant.get("category_slug"))
            if not category:
                continue
            customer = self.customers.get(trg.get("customer_id")) if trg.get("customer_id") else None
            result = compose(category, merchant, trg, customer)
            for key in ("body", "cta", "send_as", "suppression_key", "rationale"):
                self.assertIn(key, result)
            self.assertTrue(result["body"].strip(), f"empty body for {trg['id']}")
            self.assertIn(result["cta"], ("binary", "open_ended", "none"))
            self.assertIn(result["send_as"], ("vera", "merchant_on_behalf"))
            composed += 1
        self.assertEqual(composed, len(self.triggers))

    def test_customer_scope_triggers_send_as_merchant_on_behalf(self):
        for trg in self.triggers.values():
            if trg.get("scope") != "customer" or not trg.get("customer_id"):
                continue
            merchant = self.merchants.get(trg.get("merchant_id"))
            category = self.categories.get(merchant.get("category_slug")) if merchant else None
            customer = self.customers.get(trg["customer_id"])
            if not (merchant and category and customer):
                continue
            result = compose(category, merchant, trg, customer)
            self.assertEqual(result["send_as"], "merchant_on_behalf", trg["id"])

    def test_no_fabricated_offer_when_merchant_has_none(self):
        # Find a merchant with zero active offers and a competitor_opened / festival trigger,
        # assert the composed body doesn't claim a specific offer that isn't theirs.
        for trg in self.triggers.values():
            if trg.get("kind") not in ("competitor_opened", "festival_upcoming"):
                continue
            merchant = self.merchants.get(trg.get("merchant_id"))
            if not merchant:
                continue
            active = [o for o in merchant.get("offers", []) if o.get("status") == "active"]
            if active:
                continue
            category = self.categories.get(merchant.get("category_slug"))
            if not category:
                continue
            result = compose(category, merchant, trg, None)
            # None of the category's OTHER offer titles should appear verbatim
            other_titles = [o["title"] for o in category.get("offer_catalog", [])]
            for title in other_titles:
                self.assertNotIn(title, result["body"], f"fabricated offer '{title}' for merchant with no active offers")

    def test_no_double_question_mark_outside_quotes(self):
        """Anti-pattern check: at most one bot-authored CTA question per message."""
        import re
        for trg in list(self.triggers.values())[:100]:
            merchant = self.merchants.get(trg.get("merchant_id"))
            if not merchant:
                continue
            category = self.categories.get(merchant.get("category_slug"))
            if not category:
                continue
            customer = self.customers.get(trg.get("customer_id")) if trg.get("customer_id") else None
            result = compose(category, merchant, trg, customer)
            body = result["body"]
            # strip quoted spans (merchant's own words) before counting
            stripped = re.sub(r'"[^"]*"', "", body)
            self.assertLessEqual(stripped.count("?"), 1, f"{trg['id']}: {body}")

    def test_taboo_words_scrubbed(self):
        for slug, category in self.categories.items():
            taboo = [t.split(" (")[0].lower() for t in (category.get("voice", {}) or {}).get("vocab_taboo", [])]
            for trg in self.triggers.values():
                merchant = self.merchants.get(trg.get("merchant_id"))
                if not merchant or merchant.get("category_slug") != slug:
                    continue
                customer = self.customers.get(trg.get("customer_id")) if trg.get("customer_id") else None
                result = compose(category, merchant, trg, customer)
                low = result["body"].lower()
                for t in taboo:
                    if t in ("fda-approved (use only when actually applicable)",):
                        continue
                    self.assertNotIn(t, low, f"taboo phrase '{t}' leaked into {slug} message: {result['body']}")


if __name__ == "__main__":
    unittest.main()
