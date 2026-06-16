# Backend + bundled React dashboard for the Automation Hub.
# Single image: FastAPI + autonomous engine + the same React UI Vercel serves,
# so the Render URL shows the identical dashboard (single origin).
# Build context is the repo ROOT.

# --- Stage 1: build the React dashboard ---
FROM node:20-slim AS ui
WORKDIR /ui
COPY automation-hub-dashboard/package*.json ./
RUN npm ci
COPY automation-hub-dashboard/ ./
RUN npm run build          # -> /ui/dist

# --- Stage 2: Python backend (serves the built UI from ./webui) ---
FROM python:3.11-slim
WORKDIR /app
COPY . .

# Install the stdlib trading engine (root package) + the hub web dependencies.
RUN pip install --no-cache-dir -e . \
 && pip install --no-cache-dir -r automation-hub/requirements.txt

# Bundle the React build so the backend serves the same UI as Vercel.
COPY --from=ui /ui/dist /app/automation-hub/webui

# The autonomous engine starts streaming real paper trades on boot.
ENV HUB_AUTO_ENGINE=1
WORKDIR /app/automation-hub
EXPOSE 8000

# Hosts (Render/Railway/Fly) inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
