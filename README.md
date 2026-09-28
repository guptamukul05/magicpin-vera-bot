# Vera Bot — AI Assistant for Local Business Engagement

A chat-based assistant that helps local businesses (clinics, salons, restaurants, gyms, pharmacies) stay engaged with their own customers — by turning day-to-day business signals into short, specific, WhatsApp-ready messages instead of generic marketing blasts.

---

## Basic Idea

Most small businesses don't lack marketing advice — they lack *time*. Owners are busy running the actual business and rarely act on generic tips like "post more" or "run a discount."

This project is a bot that watches for real, concrete triggers happening around a business — a performance dip, a competitor opening nearby, a customer's recall coming due, a seasonal trend, a subscription about to lapse — and turns each one into a short, natural message that's specific enough to actually act on.

The bot talks in two directions:
- **To the merchant**, nudging them about something real and timely happening in their business.
- **On behalf of the merchant, to their customers**, handling recalls, win-backs, appointment reminders, and follow-ups.

---

## Problem Statement

Build an AI assistant that:

1. Composes short, high-quality business messages by combining four layers of context — the business's category, the specific merchant's profile and performance, the customer being messaged (if any), and the trigger event that caused the message to be sent.
2. Sounds like it belongs to that category and that merchant — a dentist's clinic and a salon shouldn't sound the same, and the bot shouldn't fabricate offers, prices, or claims that aren't actually true for that business.
3. Can hold a real conversation, not just send one message — including handling replies, detecting when it's talking to an auto-responder instead of a human, recognizing when a merchant is ready to act, and knowing when to stop messaging.
4. Can run as a live service that receives context pushes and produces message decisions in real time, not just a one-off script.

The hard part isn't generating *a* message — it's generating one a busy business owner would actually read, believe, and act on, without sounding like spam.

---

## How I Solved It — Basic Approach

Instead of relying on a single large prompt to improvise a message from scratch every time, I built a **routing engine**: every incoming trigger has a `kind` (performance dip, competitor opened, recall due, milestone reached, and so on), and each kind is handled by a dedicated composer function that knows exactly which pieces of context are relevant to it.

This has one big advantage: because each handler only ever touches the specific fields it needs (a percentage, a date, an offer title, a competitor's name), the bot structurally cannot invent facts that aren't in the data. There's no risk of the bot claiming a discount that doesn't exist or a statistic that was never computed — if the data isn't there, the handler either omits that part of the message or falls back to something it can actually support.

On top of that routing layer sits:

- A **voice layer** that adapts phrasing to the business category (a dental clinic and a gym shouldn't use the same tone) and to the merchant's preferred language, including natural Hindi-English mixing where appropriate.
- A **conversation layer** that manages multi-turn replies — detecting auto-replies, recognizing when a merchant has effectively said "yes, go ahead," de-escalating hostile or off-topic replies, and gracefully ending conversations that have gone quiet instead of nagging.
- A **safety layer** that scrubs category-specific "forbidden" claims (like "guaranteed results" for a gym or "miracle cure" for a pharmacy), validates that every fact used in a message actually traces back to real data, and enforces a sensible message-length limit so nothing turns into a wall of text.

An optional language-model pass can be layered on top purely to polish phrasing — but it's off by default, and any output it produces is checked against the same fact-preservation rules before being accepted. If it fails that check, the bot falls back to its own deterministic message. This keeps the bot fully functional and predictable even with zero external API calls.

---

## Features

- **Context-aware composition** across four layers: category, merchant, customer, and trigger.
- **Trigger-specific message logic** for 25+ distinct real-world situations — performance spikes/dips, seasonal shifts, competitor activity, festivals, compliance/regulatory updates, milestones, subscription renewals, win-backs, recalls, appointment reminders, wedding/package follow-ups, chronic refill reminders, and more.
- **Category-aware voice** — dentists, salons, restaurants, gyms, and pharmacies each get phrasing and terminology suited to that business type (patients vs. clients vs. guests vs. members).
- **Bilingual messaging** — natural English and Hindi-English mixed phrasing depending on the merchant's language preference and the live conversation.
- **Anti-fabrication by design** — messages are built only from fields present in real data; unverifiable comparative claims are avoided, and offers are only referenced when they're actually active.
- **Taboo-word scrubbing** — automatically neutralizes category-specific claims that shouldn't be made (e.g. "guaranteed," "miracle," "best in city"), with a safety net for anything not explicitly listed.
- **Smart offer selection** — picks the most relevant active offer for a given situation rather than a random one.
- **Multi-turn conversation handling**:
  - Detects canned/auto-reply messages and stops pushing after a human clearly isn't responding.
  - Recognizes when a merchant has given a go-ahead and switches straight into action mode instead of re-asking questions.
  - De-escalates hostile messages once, then exits gracefully if it continues.
  - Ends conversations cleanly after repeated unanswered nudges instead of following up indefinitely.
- **Message-length and consistency guards** — call-to-action type always matches what's actually in the message, and message length is capped for readability.
- **Deterministic core** — the bot works fully offline with zero external API calls; a language-model polish pass is entirely optional and validated before use.

---

## Methodology

**1. Context ingestion**
Four types of context feed the bot: category-level data (peer benchmarks, category voice/tone, seasonal patterns, vocabulary to avoid), merchant profile (identity, active offers, performance metrics, behavioral signals), customer profile (relationship history, preferences), and trigger events (the specific thing that just happened). Each context type is versioned, so stale or duplicate pushes are safely ignored.

**2. Routing by trigger kind**
When a trigger fires, it's routed to a dedicated handler based on its kind. Each handler is written specifically for that situation — a competitor-opened trigger pulls competitor name, distance, and their offer; a milestone trigger pulls the current value and the target; a recall-due trigger pulls the service due and available slots. Nothing is handled by a generic catch-all unless the trigger kind is genuinely unrecognized, in which case the bot falls back to whatever real signals it does have rather than guessing.

**3. Draft construction**
Each handler produces a structured draft: an opening hook (the specific fact), optional supporting context (why it matters), and a call-to-action, along with metadata about which persuasion angle is being used (urgency, social proof, curiosity, and so on) and which literal facts must survive into the final message untouched.

**4. Voice and language rendering**
The draft is rendered into final text using category-specific salutation style and terminology, and a language layer that produces complete, natural sentences in either English or Hindi-English mix — rather than stitching English and Hindi words together mid-sentence.

**5. Safety and consistency pass**
Before a message is finalized, it goes through taboo-word scrubbing, a call-to-action consistency check (so the labeled CTA type always matches what's actually being asked), and a length guard that trims supporting content before ever cutting into the actual ask.

**6. Optional polish pass**
If enabled, a language model can rewrite the message for more natural phrasing. The rewrite is only accepted if every required fact is still present and no new numbers or claims have been introduced — otherwise the deterministic version is used as-is.

**7. Conversation state**
Replies are classified into categories — genuine response, auto-reply, hostile, not interested, ready to act, off-topic — and each is handled with a purpose-built response strategy, with conversation history tracked so the bot never repeats itself and knows when to stop.

---

## Tech Stack

- **Python 3**, standard library only for the core engine — no required third-party dependencies to run the bot.
- A lightweight built-in HTTP server exposing endpoints for pushing context, triggering proactive sends, handling replies, and health/metadata checks.
- An optional adapter for FastAPI/uvicorn for teams that prefer a conventional web framework, kept fully decoupled from the core logic.
- Plain JSON for all data interchange — no database required to run; state is held in memory during the process lifetime.

---

## Project Structure

```
bot.py                     HTTP server + endpoint handlers
composer.py                 Core message composition engine
reply_engine.py              Multi-turn conversation logic
conversation_handlers.py      Conversation state helpers
state_store.py                In-memory context & conversation storage
utils.py                      Language detection & text heuristics
llm_client.py                  Optional LLM polish pass
dataset/                       Sample category/merchant/customer/trigger data
tests/                          Unit and integration tests
scripts/                        Setup, run, and submission helper scripts
```

---

## Deployment Details

The bot runs as a single lightweight process with no required external services.

**Run locally**
```bash
python3 bot.py
```
The server starts on port 8080 by default (configurable via the `PORT` environment variable) and exposes health, metadata, context-push, tick, and reply endpoints over plain HTTP/JSON.

**Environment configuration**
Optional environment variables control the LLM polish pass and service metadata:
```
VERA_USE_LLM=0                 # 1 to enable optional LLM polish pass
VERA_LLM_PROVIDER=anthropic    # or openai
ANTHROPIC_API_KEY / OPENAI_API_KEY
PORT=8080
```

**Containerized deployment**
A Dockerfile is included for containerized hosting:
```bash
docker build -t vera-bot .
docker run -p 8080:8080 vera-bot
```

**Platform deployment**
The service is compatible out of the box with any Python-hosting platform (Render, Railway, Fly.io, Heroku-style PaaS, or a bare VM) since it requires no build step and no database — a running Python 3 interpreter is sufficient. Deployment configs for common platforms are included in the repository root.

**Testing**
```bash
python3 -m unittest discover tests
```
Covers message composition across the full sample dataset, language/heuristic utilities, and end-to-end conversation flows against a running instance of the server.