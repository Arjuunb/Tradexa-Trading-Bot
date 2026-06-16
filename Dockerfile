# Backend for the Automation Hub live dashboard.
# FastAPI + the autonomous strategy engine (real signals -> paper execution).
# Build context is the repo ROOT (needs both the `bot` engine and `automation-hub`).
FROM python:3.11-slim

WORKDIR /app
COPY . .

# Install the stdlib trading engine (root package) + the hub web dependencies.
RUN pip install --no-cache-dir -e . \
 && pip install --no-cache-dir -r automation-hub/requirements.txt

# The autonomous engine starts streaming real paper trades on boot.
ENV HUB_AUTO_ENGINE=1
WORKDIR /app/automation-hub
EXPOSE 8000

# Hosts (Render/Railway/Fly) inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
