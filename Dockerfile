# Vera bot — zero-dependency stdlib server, so the image is tiny and the
# build is fast (no pip install needed for the bot to run at all).
FROM python:3.12-slim

WORKDIR /app

# Copy only what's needed to run the bot (dataset is needed at runtime only
# if you want /scripts/generate_submission.py inside the container too;
# harmless to include either way, it's small).
COPY bot.py composer.py reply_engine.py state_store.py utils.py llm_client.py ./
COPY dataset ./dataset
COPY scripts ./scripts

ENV PORT=8080
ENV HOST=0.0.0.0
ENV VERA_USE_LLM=0
EXPOSE 8080

# Basic container healthcheck hitting our own /v1/healthz
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request,os,sys; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/v1/healthz', timeout=3)" || exit 1

CMD ["python3", "bot.py"]
