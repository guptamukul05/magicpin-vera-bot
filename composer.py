
from __future__ import annotations

import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils import first_name, pct, pct_abs, resolve_voice_language



PHRASES = {
    "en": {
        "worth_a_look": "Worth a look",
        "want_me_to": "Want me to",
        "heads_up": "Heads up",
        "quick_one": "Quick one",
        "noticed": "Noticed",
        "would_help": "would that help",
        "let_me_know": "Let me know",
        "reply_yes": "Reply YES to go ahead, or STOP to skip",
        "drafted_for_you": "I've drafted this for you — just say go",
        "two_min": "2-minute thing",
        "than_before": "than before",
        "in_your_area": "in your area",
        "done": "Done",
        "sending_now": "Sending now",
    },
    "hi-en": {
        "worth_a_look": "Dekhna banta hai",
        "want_me_to": "Chahenge ki main",
        "heads_up": "Ek update hai",
        "quick_one": "Chota sa update",
        "noticed": "Notice kiya",
        "would_help": "helpful rahega na",
        "let_me_know": "Batayiye",
        "reply_yes": "YES bhejiye aage badhne ke liye, ya STOP agar nahi chahiye",
        "drafted_for_you": "Maine draft kar diya hai — bas 'go' bol dijiye",
        "two_min": "2 minute ka kaam hai",
        "than_before": "pehle se",
        "in_your_area": "aapke area mein",
        "done": "Ho gaya",
        "sending_now": "Bhej rahi hoon",
    },
}
PHRASES["hi"] = PHRASES["hi-en"]  # reuse hi-en connective wrapper for hi register too


def P(lang: str, key: str) -> str:
    bank = PHRASES.get(lang, PHRASES["en"])
    return bank.get(key, PHRASES["en"].get(key, key))




def _cta_want(lang: str, action: str) -> str:
    """Build a complete, grammatical CTA instead of concatenating fragments."""
    action = (action or "").strip().rstrip("?")
    if not action:
        return "Would you like me to help?"
    # Sentence-level English is intentionally used for the mixed register too:
    # the previous fragment-level Hinglish produced phrases such as
    # "Chahenge ki main check if...", which read as machine-generated.
    return f"Want me to {action}?"


def _cta_let(lang: str, condition: str) -> str:
    """Build a complete CTA without mixing Hindi and English fragments."""
    condition = (condition or "").strip()
    if condition.lower().startswith("if "):
        return f"Let me know {condition}."
    return f"Let me know if {condition}."


def _clean_label(value: Any) -> str:
    """Turn dataset identifiers into readable copy without changing facts."""
    text = str(value or "").replace("_", " ").strip()
    # Common dataset shorthand such as 30day -> 30-day.
    text = re.sub(r"(\d+)\s*day\b", r"\1-day", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text


def _truncate(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(".,;:")
    return cut + "…"


def _format_event_time(value: Any) -> str:
    """Format an ISO-ish event timestamp without assuming it is tonight/today."""
    if not value:
        return ""
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.hour == 0 and dt.minute == 0:
            return dt.strftime("%d %b %Y")
        return dt.strftime("%d %b %Y at %I:%M %p").replace(" 0", " ")
    except (TypeError, ValueError):
        return text.replace("T", " ")


def _safe_customer_name(customer: Optional[dict]) -> str:
    value = first_name(((customer or {}).get("identity", {}) or {}).get("name"))
    return value or "there"


def _safe_business_name(merchant: dict) -> str:
    identity = (merchant or {}).get("identity", {}) or {}
    return identity.get("name") or "the business"

# ---------------------------------------------------------------------------
# Category voice helpers
# ---------------------------------------------------------------------------

_SALUTATION_STYLE = {
    "dentists": "dr",
    "salons": "first_name",
    "restaurants": "first_name",
    "gyms": "first_name",
    "pharmacies": "first_name",
}


def salutation(category_slug: str, merchant: dict) -> str:
    identity = (merchant or {}).get("identity", {}) or {}
    owner = identity.get("owner_first_name") or first_name(identity.get("name")) or "there"
    owner = str(owner).strip()
    style = _SALUTATION_STYLE.get(category_slug, "first_name")
    if style == "dr" and not owner.lower().startswith("dr"):
        return f"Dr. {owner}"
    return owner


def business_name(merchant: dict) -> str:
    return _safe_business_name(merchant)


def active_offers(merchant: dict) -> List[dict]:
    offers = (merchant or {}).get("offers", []) or []
    if not isinstance(offers, list):
        return []
    return [o for o in offers if isinstance(o, dict) and o.get("status") == "active"]


def best_active_offer_title(merchant: dict, preferred_terms: Optional[List[str]] = None) -> Optional[str]:
    offers = active_offers(merchant)
    if not offers:
        return None
    if preferred_terms:
        terms = [t.lower() for t in preferred_terms if t]
        for offer in offers:
            title = str(offer.get("title", ""))
            low = title.lower()
            if any(term in low or low in term for term in terms):
                return title
    return offers[0].get("title")


def get_digest_item(category: dict, item_id: Optional[str]) -> Optional[dict]:
    if not item_id:
        return None
    for item in category.get("digest", []) or []:
        if item.get("id") == item_id:
            return item
    return None


def peer_stats(category: dict) -> dict:
    return category.get("peer_stats", {}) or {}


# ---------------------------------------------------------------------------
# MessageDraft — the intermediate representation every handler produces
# ---------------------------------------------------------------------------

@dataclass
class MessageDraft:
    hook: str                              # the specific, verifiable opening fact
    support: str = ""                      # optional second sentence — context/why it matters
    cta: str = ""                          # the ask, last sentence
    cta_type: str = "open_ended"           # "binary" | "open_ended" | "none"
    send_as: str = "vera"                  # "vera" | "merchant_on_behalf"
    levers: List[str] = field(default_factory=list)
    citation: Optional[str] = None
    rationale: str = ""
    template_name: str = "vera_generic_v1"
    template_params: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MERCHANT-FACING, EXTERNAL-trigger handlers
# ---------------------------------------------------------------------------

def h_research_digest(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    item = get_digest_item(category, payload.get("top_item_id"))
    sal = salutation(category["slug"], merchant)
    signals = merchant.get("signals", []) or []
    cohort_note = ""
    if any("high_risk" in str(s) or "cohort" in str(s) for s in signals) and item and item.get("patient_segment"):
        audience = "patients" if category["slug"] == "dentists" else "clients"
        cohort_note = f" This is especially relevant to your {_clean_label(item['patient_segment'])} {audience}."
    if item:
        n = item.get("trial_n")
        n_txt = f"{n:,}-{'patient' if category['slug']=='dentists' else 'person'} " if isinstance(n, int) else ""
        hook = str(item.get("title", "")).rstrip(".") or "A new research finding is in this week's digest"
        source_label = item.get("source") or "this week's digest"
        support = f"{n_txt}finding, via {source_label}.{cohort_note}".strip()
        cta = _cta_want(lang, "pull the full summary and draft something your customers can read")
        citation = item.get("source")
        rationale = "External research-digest trigger; anchored on the specific digest item and cited source, with category-appropriate audience wording."
    else:
        hook = f"This week's {category['slug']} research digest just landed"
        support = "Nothing in it resolved to a specific item for your current context, so I'm flagging it lightly rather than forcing a fit."
        cta = _cta_let(lang, "you want me to go through it with you")
        citation = None
        rationale = "Digest trigger fired but no top_item_id resolved in category digest — degraded gracefully instead of fabricating a finding."
    return MessageDraft(hook, support, cta, "open_ended", "vera", ["curiosity", "reciprocity", "specificity"], citation, rationale,
                         "vera_research_digest_v1", [sal, category["slug"], (item or {}).get("title", "")])


def h_regulation_change(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    item = get_digest_item(category, payload.get("top_item_id"))
    deadline = payload.get("deadline_iso", "")
    hook = (item or {}).get("title") or "A compliance update just dropped for your category"
    support_parts = []
    if deadline:
        support_parts.append(f"Deadline: {str(deadline).split('T')[0]}.")
    if item and item.get("summary"):
        support_parts.append(str(item["summary"]).strip())
    support = " ".join(support_parts)
    cta = _cta_want(lang, "check whether this applies to your setup and flag exactly what to change")
    return MessageDraft(hook, support, cta, "binary", "vera", ["loss_aversion", "specificity"],
                         (item or {}).get("source"),
                         "Regulation-change trigger; urgency reflects the supplied compliance deadline.",
                         "vera_compliance_v1", [salutation(category["slug"], merchant), hook])


def h_festival_upcoming(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    festival = payload.get("festival", "the festival")
    days = payload.get("days_until")
    festival_date = payload.get("festival_date") or payload.get("date")
    offer = best_active_offer_title(merchant)
    if festival_date:
        hook = f"{festival} is on {str(festival_date).split('T')[0]}"
    elif days is not None:
        hook = f"{festival} is {days} days away"
    else:
        hook = f"{festival} is coming up"
    if offer:
        support = f"Your active offer is \"{offer}\"."
    else:
        category_offer_name = {
            "gyms": "gym",
            "salons": "salon",
            "restaurants": "restaurant",
            "dentists": "dental",
            "pharmacies": "pharmacy",
        }.get(category.get("slug", ""), "category")
        support = f"This is a timely window to prepare a {category_offer_name} offer or post."
    cta = _cta_want(lang, "draft a festival post around that offer") if offer else _cta_want(lang, "draft a festival post")
    return MessageDraft(hook, support, cta, "binary", "vera", ["specificity", "effort_externalization"], None,
                         "Festival trigger; uses only the supplied festival timing and the merchant's active offer when available.",
                         "vera_festival_v1", [salutation(category["slug"], merchant), str(festival), str(days or "")])


def h_competitor_opened(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    name = payload.get("competitor_name", "A new competitor")
    dist = payload.get("distance_km")
    their_offer = payload.get("their_offer")
    if dist is not None:
        hook = f"{name} opened {dist} km from you"
    else:
        hook = f"{name} opened nearby"
    support = f"They're running \"{their_offer}\" right now." if their_offer else ""
    my_offer = best_active_offer_title(merchant)
    if my_offer:
        support = (support + f" Your current offer is \"{my_offer}\".").strip()
        cta = _cta_want(lang, f"put your current offer in front of people searching {P(lang, 'in_your_area')} this week")
    else:
        cta = _cta_want(lang, "help you put together an offer")
    return MessageDraft(hook, support, cta, "binary", "vera", ["specificity"], None,
                         "Competitor-opened trigger; states the real competitor distance/offer and the merchant's own active offer without claiming an unsupported competitive advantage.",
                         "vera_competitor_v1", [salutation(category["slug"], merchant), str(name), str(dist or "")])


def h_category_trend_movement(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {})
    query = payload.get("query")
    delta = payload.get("delta_yoy")
    signal = None
    if not query:
        signals = category.get("trend_signals", [])
        if signals:
            signal = signals[0]
            query, delta = signal.get("query"), signal.get("delta_yoy")
    hook = f"\"{query}\" searches are up {pct_abs(delta)} YoY" if query and delta is not None else "A search trend just moved in your category"
    seg = payload.get("segment_age") or (signal or {}).get("segment_age")
    support = f"Segment skew: {seg}." if seg else ""
    cta = f"{P(lang,'want_me_to')} check if your listing shows up for that search yet?"
    return MessageDraft(hook, support, cta, "open_ended", "vera", ["specificity", "curiosity"], None,
                         "Category trend-movement trigger; used Google-Trends-style delta from category context only.",
                         "vera_trend_v1", [salutation(category["slug"], merchant), str(query or "")])


def h_weather_heatwave(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    temp = payload.get("temp_c") if payload.get("temp_c") is not None else payload.get("temperature")
    city = ((merchant.get("identity", {}) or {}).get("city") or "your city")
    hook = f"{temp}\u00b0C in {city} today" if temp is not None else f"Heatwave conditions in {city} today"
    support = "A same-day post can reference today's weather without changing your offer details."
    cta = _cta_want(lang, "draft a same-day post tuned to today's weather")
    return MessageDraft(hook, support, cta, "binary", "vera", ["specificity", "curiosity"], None,
                         "Weather trigger; timely and local, with no unsupported claim about footfall or search behavior.",
                         "vera_weather_v1", [salutation(category["slug"], merchant), str(temp or "")])


def h_local_news_event(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    headline = payload.get("headline") or payload.get("event") or "A local event"
    hook = str(headline).strip()
    support = ""
    cta = _cta_let(lang, "you want a short note drafted for regulars")
    return MessageDraft(hook, support, cta, "open_ended", "vera", ["specificity"], None,
                         "Local-news-event trigger; kept strictly to the supplied event/headline and avoids predicting footfall impact.",
                         "vera_local_news_v1", [salutation(category["slug"], merchant), hook])


def h_ipl_match_today(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    match = payload.get("match", "The match")
    venue = payload.get("venue")
    match_time = payload.get("match_time") or payload.get("match_time_iso") or payload.get("date")
    timing = _format_event_time(match_time)
    hook = str(match)
    if timing:
        hook += f" on {timing}"
    if venue:
        hook += f" at {venue}"
    support = ""
    cta = _cta_want(lang, "put together a match-day post")
    return MessageDraft(hook, support, cta, "binary", "vera", ["specificity", "curiosity"], None,
                         "Match trigger; uses the supplied event timing and venue instead of assuming the match is tonight.",
                         "vera_ipl_v1", [salutation(category["slug"], merchant), str(match), timing])


def h_cde_opportunity(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    item = get_digest_item(category, payload.get("digest_item_id"))
    credits = payload.get("credits")
    fee = payload.get("fee")
    hook = (item or {}).get("title") or "A CDE / professional-development session is coming up"
    parts = []
    if credits is not None:
        parts.append(f"{credits} credits")
    if fee:
        parts.append(str(fee).replace("_", " "))
    support = ", ".join(parts).capitalize() + "." if parts else ""
    cta = _cta_let(lang, "you'd like the registration link")
    return MessageDraft(hook, support, cta, "open_ended", "vera", ["specificity"], (item or {}).get("source"),
                         "CDE-opportunity trigger; informational and based only on the supplied session details.",
                         "vera_cde_v1", [salutation(category["slug"], merchant), hook])


def h_supply_alert(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {})
    molecule = payload.get("molecule", "a stocked item")
    batches = payload.get("affected_batches", [])
    hook = f"Recall notice: {molecule}" + (f", batches {', '.join(batches)}" if batches else "")
    support = "Worth checking your shelf stock against this batch list."
    cta = f"{P(lang,'want_me_to')} send the full recall notice for your records?"
    return MessageDraft(hook, support, cta, "binary", "vera", ["specificity", "loss_aversion"], None,
                         "Supply-alert trigger; urgency 5 in source data — treated as high-priority operational, factual only.",
                         "vera_supply_alert_v1", [salutation(category["slug"], merchant), molecule])


def h_category_seasonal(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {})
    trends = payload.get("trends", [])
    season = payload.get("season", "this season")
    hook = f"{season.replace('_', ' ').title()} shelf shift" if trends else f"Seasonal shift incoming: {season}"
    support = ", ".join(t.replace("_", " ") for t in trends[:3]) if trends else ""
    cta = f"{P(lang,'want_me_to')} flag the SKUs worth restocking first?"
    return MessageDraft(hook, support, cta, "open_ended", "vera", ["specificity"], None,
                         "Category-seasonal trigger; listed only the trend tags present in payload.",
                         "vera_seasonal_v1", [salutation(category["slug"], merchant), season])


# ---------------------------------------------------------------------------
# MERCHANT-FACING, INTERNAL-trigger handlers
# ---------------------------------------------------------------------------

def h_perf_spike(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    metric = _clean_label(payload.get("metric", "views"))
    delta = payload.get("delta_pct")
    baseline = payload.get("vs_baseline")
    window = payload.get("window") or "the supplied period"
    driver = payload.get("likely_driver")
    if delta is not None and isinstance(delta, (int, float)):
        hook = f"Your {metric} are up {pct_abs(delta)} over {window}"
    else:
        hook = f"Your {metric} are showing a positive movement over {window}"
    support = f"Your supplied baseline is {baseline}." if baseline is not None else ""
    if driver:
        support += f" Likely driver: {_clean_label(driver)}."
    cta = _cta_want(lang, "double down on what's working with a follow-up post")
    return MessageDraft(hook, support.strip(), cta, "binary", "vera", ["specificity", "reciprocity"], None,
                         "perf_spike internal trigger; uses the merchant's supplied delta, window, baseline, and likely driver without assuming a daily unit.",
                         "vera_perf_spike_v1", [salutation(category["slug"], merchant), metric, pct_abs(delta) if delta is not None else ""])


def h_perf_dip(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    metric = _clean_label(payload.get("metric", "calls"))
    delta = payload.get("delta_pct")
    window = payload.get("window", "7d")
    baseline = payload.get("vs_baseline")
    if delta is not None and isinstance(delta, (int, float)):
        direction = "down" if delta < 0 else "up"
        hook = f"Your {metric} are {direction} {pct_abs(delta)} over the last {window}"
    else:
        hook = f"Your {metric} are showing a change over the last {window}"
    support = f"Your supplied baseline is {baseline}." if baseline is not None else ""
    cta = _cta_want(lang, "pull up what changed and suggest a fix")
    return MessageDraft(hook, support.strip(), cta, "binary", "vera", ["loss_aversion", "specificity"], None,
                         "perf_dip internal trigger; uses the supplied window and baseline instead of assuming a daily unit.",
                         "vera_perf_dip_v1", [salutation(category["slug"], merchant), metric, pct_abs(delta) if delta is not None else ""])


def h_seasonal_perf_dip(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    metric = _clean_label(payload.get("metric", "views"))
    delta = payload.get("delta_pct")
    window = payload.get("window", "the supplied period")
    note = _clean_label(payload.get("season_note", ""))
    expected = payload.get("is_expected_seasonal")
    if delta is not None and isinstance(delta, (int, float)):
        direction = "down" if delta < 0 else "up"
        hook = f"Your {metric} are {direction} {pct_abs(delta)} over {window}"
    else:
        hook = f"Your {metric} changed over {window}"
    if expected is True and note:
        support = f"The trigger marks this as an expected seasonal pattern ({note})."
    elif note:
        support = f"Season note supplied with the trigger: {note}."
    else:
        support = "The trigger does not establish whether the movement is seasonal."
    cta = _cta_let(lang, "you want a plan for when demand picks back up")
    return MessageDraft(hook, support, cta, "open_ended", "vera", ["specificity", "reciprocity"], None,
                         "seasonal_perf_dip trigger; reassurance is used only when is_expected_seasonal is explicitly true.",
                         "vera_seasonal_dip_v1", [salutation(category["slug"], merchant), metric])


def h_milestone_reached(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    metric = _clean_label(payload.get("metric", "reviews"))
    now, target = payload.get("value_now"), payload.get("milestone_value")
    imminent = payload.get("is_imminent")
    noun = "review" if metric.lower() in ("review", "reviews", "review count") else metric
    if now is not None and target is not None and isinstance(now, (int, float)) and isinstance(target, (int, float)):
        gap = target - now
        if gap > 0:
            hook = f"{int(gap) if float(gap).is_integer() else gap} more {noun}{'' if gap == 1 else 's'} and you hit {target}"
        elif gap == 0:
            hook = f"You've reached {target} {noun}{'' if target == 1 else 's'}"
        else:
            hook = f"You've crossed {target} {noun}{'' if target == 1 else 's'}"
    else:
        if imminent:
            hook = f"You're close to a {metric} milestone"
        elif now is not None and target is not None:
            hook = f"Your {metric} milestone is at {target}"
        else:
            hook = f"You have a {metric} milestone coming up"
    support = "A milestone can be useful social proof for a Google post."
    cta = _cta_want(lang, "draft a post celebrating it") if (now is None or target is None or now < target) else _cta_want(lang, "draft a post celebrating the milestone")
    return MessageDraft(hook, support, cta, "binary", "vera", ["social_proof", "specificity"], None,
                         "milestone_reached trigger; milestone wording now distinguishes approaching, reached, and crossed states.",
                         "vera_milestone_v1", [salutation(category["slug"], merchant), str(target or "")])


def h_dormant_with_vera(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {})
    days = payload.get("days_since_last_merchant_message")
    last_topic = payload.get("last_topic", "").replace("_", " ")
    hook = f"It's been {days} days since we last spoke" if days else "It's been a while since we last spoke"
    support = f"We left off on {last_topic}." if last_topic else "No pressure — just checking in."
    cta = f"{P(lang,'let_me_know')} if you want to pick that back up, or I'll leave you be for now."
    return MessageDraft(hook, support, cta, "open_ended", "vera", ["reciprocity"], None,
                         "dormant_with_vera trigger; low-pressure re-engagement, single ask, easy opt-out built in.",
                         "vera_dormant_v1", [salutation(category["slug"], merchant), str(days or "")])


def h_review_theme_emerged(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    theme = _clean_label(payload.get("theme", ""))
    occ = payload.get("occurrences_30d")
    quote = _truncate(payload.get("common_quote", ""), 180)
    hook = f"\"{theme}\" has come up in {occ} reviews this month" if theme and occ is not None else "A review pattern is emerging"
    support = f'One reviewer put it as: "{quote}"' if quote else ""
    cta = _cta_want(lang, "draft a quick fix or a public reply addressing it")
    return MessageDraft(hook, support, cta, "binary", "vera", ["loss_aversion", "specificity"], None,
                         "review_theme_emerged trigger; quote is taken from the supplied review text and length-limited.",
                         "vera_review_theme_v1", [salutation(category["slug"], merchant), theme])


def h_renewal_due(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    days = payload.get("days_remaining")
    plan = payload.get("plan", "your plan")
    amount = payload.get("renewal_amount")
    if isinstance(days, (int, float)) and days < 0:
        hook = f"{plan} renewal was due {abs(days):g} days ago"
    elif days is not None:
        hook = f"{plan} renews in {days:g} days" if isinstance(days, (int, float)) else f"{plan} renews in {days} days"
    else:
        hook = f"{plan} renewal is coming up"
    support = f"Renewal amount: \u20b9{amount:,}." if isinstance(amount, (int, float)) else (f"Renewal amount: \u20b9{amount}." if amount else "")
    cta = P(lang, "reply_yes") if isinstance(days, (int, float)) and 0 <= days <= 14 else _cta_let(lang, "you'd like to lock it in now")
    return MessageDraft(hook, support, cta, "binary", "vera", ["loss_aversion", "specificity"], None,
                         "renewal_due trigger; negative day counts are described as overdue rather than as a future renewal.",
                         "vera_renewal_v1", [salutation(category["slug"], merchant), str(days or ""), str(amount or "")])


def h_winback_eligible(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {})
    days_exp = payload.get("days_since_expiry")
    dip = payload.get("perf_dip_pct")
    lapsed = payload.get("lapsed_customers_added_since_expiry")
    hook = f"It's been {days_exp} days since your subscription lapsed" if days_exp else "Your subscription has lapsed"
    parts = []
    if dip:
        parts.append(f"visibility is down {pct_abs(dip)}")
    if lapsed:
        parts.append(f"{lapsed} customers have gone quiet since")
    support = " and ".join(parts).capitalize() + "." if parts else ""
    cta = f"{P(lang,'want_me_to')} show you exactly what reactivating would fix first?"
    return MessageDraft(hook, support, cta, "binary", "vera", ["loss_aversion", "specificity"], None,
                         "winback_eligible trigger; every number sourced from payload (dip%, lapsed count), no generic pitch.",
                         "vera_winback_v1", [salutation(category["slug"], merchant), str(days_exp or "")])


def h_gbp_unverified(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {})
    uplift = payload.get("estimated_uplift_pct")
    path = payload.get("verification_path", "").replace("_", " ")
    hook = "Your Google Business Profile still shows as unverified"
    support = f"Verified listings in your category see roughly {pct_abs(uplift)} more visibility." if uplift else ""
    if path:
        support += f" Verification path available: {path}."
    cta = _cta_want(lang, "walk you through the verification steps")
    return MessageDraft(hook, support.strip(), cta, "binary", "vera", ["loss_aversion", "effort_externalization"], None,
                         "gbp_unverified trigger; uplift number only used if present in payload.",
                         "vera_gbp_verify_v1", [salutation(category["slug"], merchant)])


def h_curious_ask_due(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    ask_template = str(payload.get("ask_template", "")).lower()
    questions_by_cat = {
        "dentists": "What's the most-asked treatment at your clinic this week?",
        "salons": "What service are clients asking for most this week?",
        "restaurants": "What's your best-selling dish this week?",
        "gyms": "What's the one class or slot members keep asking to add?",
        "pharmacies": "What's flying off the shelf this week that surprised you?",
    }
    if "service_in_demand" in ask_template or "demand" in ask_template:
        question = questions_by_cat.get(category["slug"], "What are customers asking for most this week?")
    elif "best_seller" in ask_template or "best_selling" in ask_template:
        question = "What's your best-selling item this week?"
    elif "class" in ask_template or "slot" in ask_template:
        question = "Which class or slot are members asking for most?"
    else:
        question = questions_by_cat.get(category["slug"], "What's been working well for you this week?")
    hook = f"{P(lang,'quick_one')} — {question}"
    cta = _cta_let(lang, "I can turn the answer into a post")
    return MessageDraft(hook, "", cta, "open_ended", "vera", ["asking_the_merchant"], None,
                         f"curious_ask_due trigger ({ask_template or 'weekly cadence'}); question is selected from the supplied ask template where possible.",
                         "vera_curious_ask_v1", [salutation(category["slug"], merchant), question])


def h_active_planning_intent(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    topic = _clean_label(payload.get("intent_topic", ""))
    last_msg = _truncate(payload.get("merchant_last_message", ""), 220)
    if last_msg:
        hook = f"Building on what you said — \"{last_msg}\""
    elif topic:
        hook = f"Picking up on {topic}"
    else:
        hook = "Picking up on your planning request"
    slug = category.get("slug", "")
    if slug == "restaurants":
        artifact = "pricing, menu/offer structure, and a WhatsApp blurb"
    elif slug == "salons":
        artifact = "package structure, service flow, and a WhatsApp blurb"
    elif slug == "gyms":
        artifact = "program structure, session flow, and a WhatsApp blurb"
    elif slug == "dentists":
        artifact = "service structure, pricing, and a WhatsApp blurb"
    else:
        artifact = "offer structure, customer flow, and a WhatsApp blurb"
    support = f"I can shape {topic or 'this idea'} into {artifact}."
    cta = _cta_want(lang, "send the full draft now")
    return MessageDraft(hook, support, cta, "binary", "vera", ["effort_externalization", "reciprocity"], None,
                         "active_planning_intent trigger; planning artifact is adapted to category rather than assuming every business needs a menu.",
                         "vera_planning_v1", [salutation(category["slug"], merchant), topic])


def h_scheduled_recurring(category, merchant, trigger, customer, lang) -> MessageDraft:
    stats = peer_stats(category)
    perf = merchant.get("performance", {}) or {}
    ctr = perf.get("ctr")
    avg_ctr = stats.get("avg_ctr")
    hook = f"{P(lang,'quick_one')} check-in for the week"
    if isinstance(ctr, (int, float)) and isinstance(avg_ctr, (int, float)):
        cmp = "above" if ctr >= avg_ctr else "below"
        support = f"Your CTR is {ctr*100:.1f}%, {cmp} the {avg_ctr*100:.1f}% peer average for {category['slug']}."
    else:
        support = "Nothing urgent — just staying in touch."
    return MessageDraft(hook, support, "", "none", "vera", ["specificity"], None,
                         "scheduled_recurring cadence trigger; low urgency and no CTA pressure.",
                         "vera_weekly_checkin_v1", [salutation(category["slug"], merchant)])


# ---------------------------------------------------------------------------
# CUSTOMER-FACING handlers (send_as = merchant_on_behalf)
# ---------------------------------------------------------------------------

def _customer_name(customer: dict) -> str:
    return _safe_customer_name(customer)


def h_recall_due(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    biz = business_name(merchant)
    cname = _customer_name(customer)
    service = _clean_label(payload.get("service_due", ""))
    last = payload.get("last_service_date")
    slots = payload.get("available_slots", []) or []
    if not isinstance(slots, list):
        slots = []
    # Prefer an offer related to the recalled service instead of blindly taking the first offer.
    offer = best_active_offer_title(merchant, [service] if service else None)
    if service:
        hook = f"Hi {cname}, {biz} here \U0001F44B It's time for your {service}" + (f" (last visit {last})" if last else "")
    else:
        hook = f"Hi {cname}, {biz} here \U0001F44B Your recall is due" + (f" (last visit {last})" if last else "")
    support_parts = []
    valid_slots = [s for s in slots[:2] if isinstance(s, dict) and s.get("label")]
    if valid_slots:
        labels = " or ".join(s.get("label", "") for s in valid_slots)
        support_parts.append(f"We've got {labels} open.")
    if offer:
        support_parts.append(f"{offer}.")
    support = " ".join(support_parts)
    if valid_slots:
        opts = "/".join(str(i + 1) for i in range(len(valid_slots)))
        cta = f"Reply {opts} to pick a slot, or tell us a time that works."
    else:
        cta = "Reply to book, or tell us a time that works."
    return MessageDraft(hook, support, cta, "binary", "merchant_on_behalf", ["specificity", "effort_externalization"], None,
                         "recall_due customer trigger; real slots + a relevant active offer only.",
                         "merchant_recall_v1", [cname, service, str(len(valid_slots))])


def h_customer_lapsed_soft(category, merchant, trigger, customer, lang) -> MessageDraft:
    biz = business_name(merchant)
    cname = _customer_name(customer)
    rel = (customer or {}).get("relationship", {}) or {}
    last_visit = rel.get("last_visit")
    offer = best_active_offer_title(merchant)
    hook = f"Hi {cname}, {biz} here \U0001F44B It's been a bit since your last visit" + (f" ({last_visit})" if last_visit else "")
    support = f"We've got \"{offer}\" running right now if you'd like to come back in." if offer else "Would love to see you again."
    cta = "Reply YES if you'd like to come back, or STOP if you'd rather not hear from us."
    return MessageDraft(hook, support, cta, "binary", "merchant_on_behalf", ["reciprocity", "specificity"], None,
                         "customer_lapsed_soft trigger; avoids promising a slot unless an actual slot is supplied.",
                         "merchant_winback_v1", [cname, offer or ""])


def h_customer_lapsed_hard(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    biz = business_name(merchant)
    cname = _customer_name(customer)
    days = payload.get("days_since_last_visit")
    focus = _clean_label(payload.get("previous_focus", ""))
    hook = f"Hi {cname}, {biz} here \U0001F44B It's been {days} days since we last saw you" if days is not None else f"Hi {cname}, {biz} here \U0001F44B It's been a while"
    support = f"Last time you were focused on {focus} — happy to pick that back up whenever you're ready." if focus else "No pressure — the door's open whenever you're ready."
    cta = "Reply YES if you'd like to hear what's available, or STOP if you'd rather not hear from us again."
    return MessageDraft(hook, support, cta, "binary", "merchant_on_behalf", ["reciprocity"], None,
                         "customer_lapsed_hard trigger; warmer, no-pressure tone without promising an unverified comeback slot.",
                         "merchant_winback_hard_v1", [cname, str(days or "")])


def h_appointment_tomorrow(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    biz = business_name(merchant)
    cname = _customer_name(customer)
    time_label = payload.get("time_label") or payload.get("slot_label") or "tomorrow"
    appointment_date = payload.get("appointment_date") or payload.get("date")
    date_text = str(appointment_date).split("T")[0] if appointment_date else ""
    hook = f"Hi {cname}, {biz} here \U0001F44B Reminder: your appointment is {time_label}"
    if date_text and date_text not in str(time_label):
        hook += f" on {date_text}"
    cta = "Reply 1 to confirm, 2 to reschedule."
    return MessageDraft(hook, "", cta, "binary", "merchant_on_behalf", ["specificity"], None,
                         "appointment reminder; uses supplied slot/date and does not independently claim an unverified appointment time.",
                         "merchant_appt_reminder_v1", [cname, str(time_label)])


def h_wedding_package_followup(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    biz = business_name(merchant)
    cname = _customer_name(customer)
    wedding_date = payload.get("wedding_date")
    days_to = payload.get("days_to_wedding")
    next_step = _clean_label(payload.get("next_step_window_open", ""))
    hook = f"Hi {cname}, {biz} here \U0001F44B {days_to} days to go!" if days_to is not None else f"Hi {cname}, {biz} here \U0001F44B Wedding countdown update"
    support = f"Your trial's done — next up is the {next_step}." if next_step else "Time to lock in the next step."
    if wedding_date:
        support += f" Wedding date: {str(wedding_date).split('T')[0]}."
    cta = "Want me to hold your slot for it?"
    return MessageDraft(hook, support, cta, "binary", "merchant_on_behalf", ["specificity", "effort_externalization"], None,
                         "wedding_package_followup trigger; uses supplied countdown, next step, and wedding date without inventing a package name.",
                         "merchant_bridal_v1", [cname, str(days_to or "")])


def h_trial_followup(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    biz = business_name(merchant)
    cname = _customer_name(customer)
    trial_date = payload.get("trial_date")
    options = payload.get("next_session_options", []) or []
    valid_options = [o for o in options[:2] if isinstance(o, dict) and o.get("label")]
    hook = f"Hi {cname}, {biz} here \U0001F44B How was your trial{(' on ' + str(trial_date)) if trial_date else ''}?"
    if valid_options:
        labels = " or ".join(o.get("label", "") for o in valid_options)
        support = f"Next session options: {labels}."
        cta = "Reply 1 or 2 to pick one, or STOP if it's not for you." if len(valid_options) == 2 else "Reply YES to lock it in, or STOP if it's not for you."
    else:
        support = "Would love to have you back for a full session."
        cta = "Reply YES to book, or STOP if it's not for you."
    return MessageDraft(hook, support, cta, "binary", "merchant_on_behalf", ["specificity", "reciprocity"], None,
                         "trial_followup trigger; mentions only session options actually present in payload.",
                         "merchant_trial_followup_v1", [cname])


def h_chronic_refill_due(category, merchant, trigger, customer, lang) -> MessageDraft:
    payload = trigger.get("payload", {}) or {}
    biz = business_name(merchant)
    cname = _customer_name(customer)
    molecules = payload.get("molecule_list", []) or []
    if not isinstance(molecules, list):
        molecules = []
    molecules = [str(m) for m in molecules if m]
    runs_out = payload.get("stock_runs_out_iso", "")
    delivery = payload.get("delivery_address_saved")
    medicine_text = ", ".join(molecules[:3])
    if len(molecules) > 3:
        medicine_text += f" and {len(molecules) - 3} more"
    hook = f"Hi {cname}, {biz} here \U0001F44B Your regular refill ({medicine_text}) looks due soon" if medicine_text else f"Hi {cname}, {biz} here \U0001F44B Your regular refill looks due soon"
    support = f"Stock runs out around {str(runs_out).split('T')[0]}." if runs_out else ""
    if delivery:
        support += " Delivery to your saved address is available."
    cta = "Reply YES to reorder, or STOP if you've already restocked elsewhere."
    return MessageDraft(hook, support.strip(), cta, "binary", "merchant_on_behalf", ["specificity", "effort_externalization"], None,
                         "chronic_refill_due trigger; medicine names and delivery status are taken from payload and the list is length-limited.",
                         "merchant_refill_v1", [cname, ", ".join(molecules)])


# ---------------------------------------------------------------------------
# Generic fallback — used for any kind not special-cased above, and for
# generated triggers whose payload is a placeholder (see generate_dataset.py
# expand_triggers: {"placeholder": True, "metric_or_topic": kind}). In that
# degenerate case we fall back to the merchant's own real signals/performance
# rather than inventing anything about the trigger itself.
# ---------------------------------------------------------------------------

def h_generic_fallback(category, merchant, trigger, customer, lang) -> MessageDraft:
    kind = _clean_label(trigger.get("kind", "update"))
    payload = trigger.get("payload", {}) or {}
    is_placeholder = bool(payload.get("placeholder"))
    scope = trigger.get("scope", "merchant")

    facts = []
    if not is_placeholder:
        for k, v in payload.items():
            if k in ("placeholder", "metric_or_topic") or v in (None, "", [], {}):
                continue
            label = _clean_label(k)
            if isinstance(v, bool):
                facts.append(f"{label}: {'yes' if v else 'no'}")
            elif isinstance(v, (int, float)):
                facts.append(f"{label}: {v}")
            elif isinstance(v, str) and len(v) < 60:
                facts.append(f"{label}: {_clean_label(v)}")
            if len(facts) >= 3:
                break
    fact_str = "; ".join(facts)

    if scope == "customer" and customer:
        biz = business_name(merchant)
        cname = _customer_name(customer)
        hook = f"Hi {cname}, {biz} here \U0001F44B Just a quick note"
        support = fact_str if fact_str else "Wanted to check in."
        cta = "Reply if you'd like to hear more, or STOP to opt out."
        return MessageDraft(hook, support, cta, "binary", "merchant_on_behalf", ["reciprocity"], None,
                             f"Generic fallback for unmapped customer-scope kind '{kind}'" +
                             ("; placeholder payload degraded to a light-touch note." if is_placeholder else "; surfaced only short payload fields."),
                             "merchant_generic_v1", [cname])

    sal = salutation(category["slug"], merchant)
    signals = merchant.get("signals", []) or []
    perf = merchant.get("performance", {}) or {}
    if fact_str:
        hook = f"{P(lang,'heads_up')}: {kind}"
        support = fact_str
    elif signals:
        sig = _clean_label(str(signals[0]).replace(":", " — "))
        hook = f"{P(lang,'noticed')} something on your profile: {sig}"
        support = f"Flagged this because of the '{kind}' check that just ran."
    elif perf:
        views = perf.get("views")
        hook = f"{P(lang,'quick_one')} on your account ({kind})"
        support = f"Your last snapshot: {views} views in the last {perf.get('window_days', 30)} days." if views is not None else ""
    else:
        hook = f"{P(lang,'quick_one')} — {kind} update"
        support = "Nothing urgent, just staying in the loop."
    cta = _cta_let(lang, "you'd like me to dig into this further")
    return MessageDraft(hook, support, cta, "open_ended", "vera", ["specificity"] if (fact_str or signals) else [], None,
                         f"Generic fallback for unmapped/placeholder kind '{kind}'; only short real payload fields or merchant signals are surfaced.",
                         "vera_generic_v1", [sal, kind])


KIND_HANDLERS = {
    "research_digest": h_research_digest,
    "regulation_change": h_regulation_change,
    "festival_upcoming": h_festival_upcoming,
    "competitor_opened": h_competitor_opened,
    "category_trend_movement": h_category_trend_movement,
    "weather_heatwave": h_weather_heatwave,
    "local_news_event": h_local_news_event,
    "ipl_match_today": h_ipl_match_today,
    "cde_opportunity": h_cde_opportunity,
    "supply_alert": h_supply_alert,
    "category_seasonal": h_category_seasonal,
    "perf_spike": h_perf_spike,
    "perf_dip": h_perf_dip,
    "seasonal_perf_dip": h_seasonal_perf_dip,
    "milestone_reached": h_milestone_reached,
    "dormant_with_vera": h_dormant_with_vera,
    "review_theme_emerged": h_review_theme_emerged,
    "renewal_due": h_renewal_due,
    "winback_eligible": h_winback_eligible,
    "gbp_unverified": h_gbp_unverified,
    "curious_ask_due": h_curious_ask_due,
    "active_planning_intent": h_active_planning_intent,
    "scheduled_recurring": h_scheduled_recurring,
    "recall_due": h_recall_due,
    "customer_lapsed_soft": h_customer_lapsed_soft,
    "customer_lapsed_hard": h_customer_lapsed_hard,
    "appointment_tomorrow": h_appointment_tomorrow,
    "wedding_package_followup": h_wedding_package_followup,
    "trial_followup": h_trial_followup,
    "chronic_refill_due": h_chronic_refill_due,
}


# ---------------------------------------------------------------------------
# Assembly: draft -> final WhatsApp body text
# ---------------------------------------------------------------------------

_TABOO_REPLACEMENTS = {
    "guaranteed": "expected",
    "100% safe": "well-tolerated",
    "completely cure": "help manage",
    "miracle": "notable",
    "best in city": "well-reviewed locally",
    "guaranteed glow": "a visible improvement",
    "permanent results": "long-lasting results",
    "instant transformation": "a quick visible change",
    "best food in city": "a strong local following",
    "guaranteed packed house": "a strong turnout",
    "miracle marketing": "a strong marketing push",
    "viral guarantee": "strong reach potential",
    "guaranteed weight loss": "steady progress",
    "shred in 7 days": "visible progress in weeks",
    "miracle transformation": "steady transformation",
    "fastest results": "faster results",
    "miracle cure": "a supportive option",
    "guaranteed result": "a likely improvement",
}


def _scrub_taboo(text: str, category: dict) -> str:
    taboo = (category.get("voice", {}) or {}).get("vocab_taboo", []) or []
    out = text
    for phrase in taboo:
        key = phrase.split(" (")[0].strip().lower()
        replacement = _TABOO_REPLACEMENTS.get(key)
        if not replacement:
            continue
        pattern = re.compile(re.escape(key), re.IGNORECASE)
        out = pattern.sub(replacement, out)
    return out


def _assemble_body(draft: MessageDraft, sal: str, is_customer_facing: bool) -> str:
    sentences = []
    hook = draft.hook.strip()
    if is_customer_facing:
        sentences.append(hook if hook.endswith((".", "!", "?", "\U0001F44B", "\U0001F9B7")) else hook + ".")
    else:
        joined = f"{sal}, {hook}".rstrip(".")
        sentences.append(joined if joined.endswith(("?", "!", "…")) else joined + ".")
    if draft.support:
        s = draft.support.strip()
        sentences.append(s if s.endswith((".", "!", "?")) else s + ".")
    if draft.citation and draft.citation not in draft.support:
        if sentences:
            sentences[-1] = sentences[-1].rstrip(".") + f" — {draft.citation}."
    if draft.cta and draft.cta_type != "none":
        cta = draft.cta.strip()
        sentences.append(cta if cta.endswith((".", "!", "?")) else cta + ".")
    body = " ".join(s for s in sentences if s)
    body = re.sub(r"\s+", " ", body).strip()
    body = re.sub(r"\.{2,}", ".", body)
    # Keep WhatsApp copy compact; preserve the CTA when possible.
    if len(body) > 900:
        tail = ""
        if draft.cta and draft.cta_type != "none":
            tail = " " + draft.cta.strip()
        head_limit = max(200, 900 - len(tail) - 1)
        body = body[:head_limit].rsplit(" ", 1)[0].rstrip(".,;:") + "…" + tail
    return body


def compose_message(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
    conversation_history_texts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """The main entry point. Matches challenge-brief.md section 5/7.1 contract."""
    kind = trigger.get("kind", "")
    handler = KIND_HANDLERS.get(kind, h_generic_fallback)

    merchant_langs = (merchant.get("identity", {}) or {}).get("languages", [])
    lang = resolve_voice_language(merchant_langs, conversation_history_texts)
    draft = handler(category, merchant, trigger, customer, lang)

    is_customer_facing = draft.send_as == "merchant_on_behalf"
    sal = salutation(category.get("slug", ""), merchant)
    body = _assemble_body(draft, sal, is_customer_facing)
    body = _scrub_taboo(body, category)

    # Optional LLM polish pass (disabled by default — see llm_client.py).
    # Re-run the deterministic scrubber and length guard after the model too,
    # so optional polishing cannot reintroduce taboo wording or giant output.
    try:
        from llm_client import rewrite_with_llm
        system_prompt = (
            "You write short WhatsApp messages for magicpin's Vera assistant, "
            f"in a {category.get('voice', {}).get('tone', 'peer')} voice for the "
            f"{category.get('slug','')} category. Never invent facts. Preserve all "
            "names, dates, prices, numbers, offers, and event details exactly."
        )
        facts_prompt = f"Language register to use: {lang}. Preserve the factual content exactly."
        polished = rewrite_with_llm(body, system_prompt, facts_prompt)
        if polished:
            body = _scrub_taboo(polished.strip(), category)
            if len(body) > 900:
                body = _truncate(body, 900)
    except Exception:
        # Optional polish must never make the deterministic composer fail.
        pass

    suppression_key = trigger.get("suppression_key") or f"{kind}:{merchant.get('merchant_id','')}:{trigger.get('id','')}"

    return {
        "body": body,
        "cta": draft.cta_type,
        "send_as": draft.send_as,
        "suppression_key": suppression_key,
        "rationale": draft.rationale,
        "template_name": draft.template_name,
        "template_params": draft.template_params,
        "levers": draft.levers,
        "language": lang,
    }


# Convenience alias matching the exact signature in challenge-brief.md 7.1
def compose(category: dict, merchant: dict, trigger: dict, customer: Optional[dict] = None) -> dict:
    result = compose_message(category, merchant, trigger, customer)
    return {
        "body": result["body"],
        "cta": result["cta"],
        "send_as": result["send_as"],
        "suppression_key": result["suppression_key"],
        "rationale": result["rationale"],
    }


