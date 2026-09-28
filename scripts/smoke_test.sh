set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/5  Python version =="
python3 --version

echo "== 2/5  Regenerating expanded dataset (deterministic, fixed seed) =="
python3 dataset/generate_dataset.py --seed-dir dataset --out expanded

echo "== 3/5  Unit tests (utils + composer, pure functions, no server) =="
python3 -m unittest tests.test_utils tests.test_composer -v

echo "== 4/5  Integration tests (spins up the real bot.py HTTP server) =="
python3 -m unittest tests.test_integration -v

echo "== 5/5  Regenerating submission.jsonl from the 30 canonical test pairs =="
python3 scripts/generate_submission.py

echo
echo "ALL CHECKS PASSED."
echo "submission.jsonl is up to date at: $(pwd)/submission.jsonl"
echo "Next: deploy (see RUNBOOK.md section 3), then point judge_simulator.py at your public URL."
