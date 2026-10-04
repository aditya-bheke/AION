# AION validation sandbox: runs AI-generated patches (tests + staging) in isolation.
# AION starts it with --network none, --read-only, --cap-drop ALL, --user 1000:1000 and
# CPU/memory/process limits (backend/aion/validation/sandbox.py).
#
# The image must contain the monitored service's runtime dependencies. This one matches the
# demo orders-service; a real deployment would build one image per service from its own
# requirements (or reuse the service's CI image).
FROM python:3.10-slim

RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "httpx>=0.27" "pytest>=8.0" \
 && useradd --uid 1000 --create-home runner

USER 1000
WORKDIR /work
