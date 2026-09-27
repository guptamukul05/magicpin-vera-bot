#!/usr/bin/env bash
# scripts/run_judge_simulator.sh — configure + run the provided judge_simulator.py
# against a bot that's already running (locally or deployed).
#
# Usage:
#   BOT_URL=http://localhost:8080 LLM_PROVIDER=anthropic LLM_API_KEY=sk-ant-... \
#     ./scripts/run_judge_simulator.sh [scenario]
#
# scenario defaults to "all" (warmup + auto_reply_hell + intent_transition + hostile).
# Other options: warmup | phase2_short | auto_reply_hell | intent_transition | hostile | full_evaluation
#
# judge_simulator.py's LLM-scored dimensions (specificity/category-fit/etc.)
# need a real LLM_API_KEY for the *judge's own reasoning* — this is separate
# from and unrelated to whether your bot itself uses an LLM (it doesn't, by
# default — composer.py is rule-based).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${BOT_URL:=http://localhost:8080}"
: "${LLM_PROVIDER:=openai}"
: "${LLM_API_KEY:?Set LLM_API_KEY to a real key for whichever LLM_PROVIDER you choose (openai/anthropic/gemini/deepseek/groq/openrouter/ollama)}"
: "${LLM_MODEL:=}"
SCENARIO="${1:-all}"

python3 - "$SCENARIO" <<'PYEOF'
import re
import sys
import os

scenario = sys.argv[1]
path = "judge_simulator.py"
with open(path, encoding="utf-8") as f:
    src = f.read()

src = re.sub(r'^BOT_URL = .*$', f'BOT_URL = "{os.environ["BOT_URL"]}"', src, flags=re.M)
src = re.sub(r'^LLM_PROVIDER = .*$', f'LLM_PROVIDER = "{os.environ["LLM_PROVIDER"]}"', src, flags=re.M)
src = re.sub(r'^LLM_API_KEY = .*$', f'LLM_API_KEY = "{os.environ["LLM_API_KEY"]}"', src, flags=re.M)
src = re.sub(r'^LLM_MODEL = .*$', f'LLM_MODEL = "{os.environ.get("LLM_MODEL","")}"', src, flags=re.M)
src = re.sub(r'^TEST_SCENARIO = .*$', f'TEST_SCENARIO = "{scenario}"', src, flags=re.M)

with open("/tmp/judge_simulator_configured.py", "w", encoding="utf-8") as f:
    f.write(src)
print("Configured a temp copy at /tmp/judge_simulator_configured.py -- your real judge_simulator.py is untouched.")
PYEOF

python3 /tmp/judge_simulator_configured.py
