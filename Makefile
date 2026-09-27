.PHONY: help dataset test test-unit test-integration submission run docker-build docker-run smoke clean

help:
	@echo "make dataset          - regenerate expanded/ from dataset/ seeds (deterministic)"
	@echo "make test             - run all tests (unit + integration)"
	@echo "make test-unit        - run only utils/composer unit tests (fast, no server)"
	@echo "make test-integration - spin up bot.py and run the HTTP integration suite"
	@echo "make submission       - regenerate submission.jsonl from the 30 canonical test pairs"
	@echo "make run              - run the bot locally on :8080"
	@echo "make docker-build     - build the Docker image"
	@echo "make docker-run       - run the Docker image on :8080"
	@echo "make smoke            - full pre-flight check (dataset + tests + submission)"
	@echo "make clean            - remove generated dataset/submission artifacts"

dataset:
	python3 dataset/generate_dataset.py --seed-dir dataset --out expanded

test: test-unit test-integration

test-unit:
	python3 -m unittest tests.test_utils tests.test_composer -v

test-integration:
	python3 -m unittest tests.test_integration -v

submission: dataset
	python3 scripts/generate_submission.py

run:
	bash scripts/run_local.sh

docker-build:
	docker build -t magicpin-vera-bot .

docker-run:
	docker run --rm -p 8080:8080 --env-file .env magicpin-vera-bot 2>/dev/null || \
	docker run --rm -p 8080:8080 magicpin-vera-bot

smoke:
	bash scripts/smoke_test.sh

clean:
	rm -rf expanded submission.jsonl __pycache__ tests/__pycache__ .pytest_cache
