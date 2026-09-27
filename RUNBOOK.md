# RUNBOOK — every command, start to finish

This is the literal, copy-pasteable sequence to go from this zip to a
public URL to a submitted `submission.jsonl`. Every command below has
already been run once during development (see "Verified" notes) so you
know what output to expect.

Requirements: **Python 3.9+ only**. Nothing else is required for the bot
itself. Docker is only needed if you choose the Docker deploy path in §3.

---

## 0. Unzip and look around

```bash
unzip magicpin-vera-bot.zip
cd magicpin-vera-bot
python3 --version        # need 3.9+
ls
```

---

## 1. Regenerate the dataset (deterministic — same output every time)

The zip already ships a generated `expanded/` dataset and `submission.jsonl`
so you can skip straight to §2/§4 if you just want to verify things work.
To regenerate from scratch (e.g. after editing `dataset/*.json`):

```bash
python3 dataset/generate_dataset.py --seed-dir dataset --out expanded
```

**Verified output:**
```
Generated dataset:
  50 merchants
  200 customers
  100 triggers
  30 test pairs
Written to expanded/
```

---

## 2. Run the test suite

```bash
# Fast unit tests — utils heuristics + composer against ALL 100 triggers
# in the dataset (not just the 30 canonical ones). No server needed.
python3 -m unittest tests.test_utils tests.test_composer -v

# Integration test — boots the REAL bot.py server on a scratch port and
# replays the auto-reply / intent-transition / hostile / not-interested
# scenarios over real HTTP, plus the /v1/context, /v1/tick idempotency
# and dedup behavior.
python3 -m unittest tests.test_integration -v
```

**Verified output:** `Ran 16 tests ... OK` / `Ran 5 tests ... OK` / `Ran 12
tests ... OK` — 33 tests total, all green.

Or run everything (dataset regen + both test suites + submission
regeneration) in one shot:

```bash
bash scripts/smoke_test.sh
# or: make smoke
```

---

## 3. Run the bot locally

```bash
python3 bot.py
# or: bash scripts/run_local.sh
# or: PORT=9000 python3 bot.py    (custom port)
```

You should see:
```
YYYY-MM-DD HH:MM:SS INFO Vera bot listening on http://0.0.0.0:8080  (PID xxxxx)
YYYY-MM-DD HH:MM:SS INFO Endpoints: GET /v1/healthz, GET /v1/metadata, POST /v1/context, POST /v1/tick, POST /v1/reply, POST /v1/teardown
```

In a second terminal, sanity-check it:

```bash
curl -s http://localhost:8080/v1/healthz | python3 -m json.tool
curl -s http://localhost:8080/v1/metadata | python3 -m json.tool

# Push one category + one merchant + one trigger, then tick:
curl -s -X POST http://localhost:8080/v1/context \
  -H 'Content-Type: application/json' \
  -d @- <<'EOF' | python3 -m json.tool
{"scope":"category","context_id":"dentists","version":1,
 "payload": $(python3 -c "import json;print(json.dumps(json.load(open('dataset/categories/dentists.json'))))"),
 "delivered_at":"2026-04-26T09:00:00Z"}
EOF
```

(The `curl` one-liners above get unwieldy for large payloads — for real
testing, use `scripts/run_judge_simulator.sh` or `tests/test_integration.py`,
both of which push full real context payloads programmatically.)

Stop the server with `Ctrl+C`.

### Optional: enable the LLM polish pass

Off by default (fully deterministic, zero network calls). To turn on:

```bash
export VERA_USE_LLM=1
export VERA_LLM_PROVIDER=anthropic          # or: openai
export ANTHROPIC_API_KEY=sk-ant-...         # or OPENAI_API_KEY
python3 bot.py
```

---

## 4. Generate / regenerate `submission.jsonl`

```bash
python3 scripts/generate_submission.py
# or: make submission
```

This calls `bot.compose()` directly (no HTTP, no server needed) for each
of the 30 canonical test pairs in `expanded/test_pairs.json` and writes
`submission.jsonl` in the exact shape challenge-brief.md §7.2 specifies:

```json
{"test_id": "T01", "body": "...", "cta": "open_ended", "send_as": "vera", "suppression_key": "...", "rationale": "..."}
```

**Verified output (tail):**
```
[OK] T29 (recall_due, 0.0ms): Hi Diya, Zen Yoga Studio here 👋 Your recall is due...
[OK] T30 (regulation_change, 0.1ms): Dr. Meera, DCI revised radiograph dose limits...
Wrote 30 lines to submission.jsonl
All bodies non-empty. Good to submit.
```

Every composition finishes in well under a millisecond (rule-based, no
network) — nowhere close to the 30s budget in the testing brief.

---

## 5. Deploy to a public URL

Pick ONE of these. All of them run the exact same `bot.py` with no build
step required (stdlib only).

### 5a. Render (recommended — free tier, `render.yaml` included)

1. Push this repo to GitHub (or GitLab).
2. On [render.com](https://render.com) → **New +** → **Blueprint** → point
   at your repo. Render reads `render.yaml` automatically and creates the
   service (start command `python3 bot.py`, health check `/v1/healthz`).
3. Once deployed, your bot is live at `https://<your-service-name>.onrender.com`.
4. Verify: `curl https://<your-service-name>.onrender.com/v1/healthz`

### 5b. Railway (`railway.json` included)

```bash
npm install -g @railway/cli     # one-time
railway login
railway init
railway up
railway domain                  # prints your public URL
```

### 5c. Fly.io

```bash
curl -L https://fly.io/install.sh | sh    # one-time
fly launch --no-deploy                     # accept defaults; it detects Python
fly secrets set VERA_USE_LLM=0
fly deploy
fly status                                 # prints your public URL
```

### 5d. Docker (any host that runs containers — your own VM, ECS, GCP Run, etc.)

```bash
docker build -t magicpin-vera-bot .
docker run -d -p 8080:8080 --name vera-bot magicpin-vera-bot
# or: docker compose up -d --build
curl http://localhost:8080/v1/healthz
```

Push the built image to your registry of choice and deploy it however your
target platform expects (`docker push`, then reference the image in
Cloud Run / ECS / etc.). No Dockerfile changes needed per-platform.

### 5e. Heroku-style PaaS (`Procfile` included)

```bash
heroku create your-vera-bot
git push heroku main
heroku open
```

### 5f. Any bare VM / server you already have SSH access to

```bash
scp -r magicpin-vera-bot/ user@your-server:/opt/vera-bot
ssh user@your-server
cd /opt/vera-bot
nohup python3 bot.py > bot.log 2>&1 &
# put a reverse proxy (nginx/Caddy) in front for TLS + your public URL
```

---

## 6. Run the provided `judge_simulator.py` against your deployment

```bash
export BOT_URL="https://<your-public-url>"      # from §5
export LLM_PROVIDER="openai"                    # judge's own scoring LLM — separate from your bot
export LLM_API_KEY="sk-..."                      # a real key for LLM_PROVIDER
bash scripts/run_judge_simulator.sh all
```

This configures a **temp copy** of `judge_simulator.py` (your real file is
never modified) with your `BOT_URL`/`LLM_PROVIDER`/`LLM_API_KEY`, and runs
it. See `scripts/run_judge_simulator.sh` header comment for individual
scenario names (`warmup`, `auto_reply_hell`, `intent_transition`,
`hostile`, `full_evaluation`, etc.) if you want to run one at a time.

Note: `LLM_API_KEY` here is for the **judge's own reasoning/scoring calls**
(it needs an LLM to grade specificity, category-fit, etc.) — it is
unrelated to whether your bot itself calls an LLM (by default it doesn't;
see §3 "Optional: enable the LLM polish pass").

---

## 7. Submission details

What to submit (per challenge-brief.md §7 / §16 and challenge-testing-brief.md §2):

1. **This entire repo** (or at minimum: `bot.py`, `composer.py`,
   `reply_engine.py`, `conversation_handlers.py`, `state_store.py`,
   `utils.py`, `llm_client.py`, `submission.jsonl`, `README.md`).
2. **`submission.jsonl`** — already generated at the repo root (§4 above);
   regenerate any time with `python3 scripts/generate_submission.py`.
3. **Your public deployment URL** from §5 — this is what the live judge
   harness (`POST /v1/context`, `/v1/tick`, `/v1/reply`) will call.
4. **`GET /v1/metadata`** on your deployed URL — fill in
   `VERA_TEAM_NAME` / `VERA_TEAM_MEMBERS` / `VERA_CONTACT_EMAIL` env vars
   (see `.env.example`) before your final deploy so this reports your
   actual team info, not the placeholder defaults.

**Where to submit:** The challenge microsite at
`https://magicpin.com/vera/ai-challenge` redirects to
`https://partners.magicpin.com/vera/ai-challenge`. That partner portal is
authenticated and this environment couldn't reach past the login wall, so
the exact submission form/deadline/prize details in challenge-brief.md
§14 are marked as placeholders in the source brief itself
(*"placeholders — fill in for your run"*) — confirm the live window and
submission mechanics on that portal directly (log in with your
magicpin-partner account) before your final submit, rather than relying on
anything cached here.

### Final pre-submit checklist

```bash
bash scripts/smoke_test.sh              # all tests green + submission.jsonl fresh
curl https://<your-url>/v1/healthz      # 200 OK on your live deployment
curl https://<your-url>/v1/metadata     # your real team info, not placeholders
cat submission.jsonl | wc -l            # should print 30
```
