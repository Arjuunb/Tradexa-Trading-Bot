# Backend + bundled React apps for the Automation Hub.
# Single image: FastAPI + autonomous engine + two SPAs on one origin —
#   • the public landing / auth / settings site (tradexa-landing) at  "/"
#   • the session-gated trading dashboard (automation-hub-dashboard) at "/app"
# Build context is the repo ROOT.

# --- Stage 1: build the trading dashboard (served under /app) ---
FROM node:20-slim AS ui
WORKDIR /ui
COPY automation-hub-dashboard/package*.json ./
RUN npm ci
COPY automation-hub-dashboard/ ./
# base "/app/" so the dashboard's assets resolve while the landing owns "/assets"
ENV DASHBOARD_BASE=/app/
RUN npm run build          # -> /ui/dist

# --- Stage 2: build the landing / auth / settings site (served at /) ---
FROM node:20-slim AS landing
WORKDIR /landing
COPY tradexa-landing/package*.json ./
RUN npm ci
COPY tradexa-landing/ ./
# "Launch Bot" and post-login point at the dashboard on the same origin
ENV VITE_APP_URL=/app
RUN npm run build          # -> /landing/dist

# --- Stage 3: Python backend (serves both builds) ---
FROM python:3.11-slim
WORKDIR /app
COPY . .

# Install the stdlib trading engine (root package) + the hub web dependencies.
RUN pip install --no-cache-dir -e . \
 && pip install --no-cache-dir -r automation-hub/requirements.txt

# Bundle both React builds so the backend serves them on one origin.
COPY --from=ui /ui/dist /app/automation-hub/webui
COPY --from=landing /landing/dist /app/automation-hub/landing

# The autonomous engine starts streaming real paper trades on boot.
ENV HUB_AUTO_ENGINE=1
WORKDIR /app/automation-hub
EXPOSE 8000

# Hosts (Render/Railway/Fly) inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
