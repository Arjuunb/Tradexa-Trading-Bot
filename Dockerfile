# Backend + bundled React apps for the Automation Hub.
# Single image: FastAPI + autonomous engine + two SPAs on one origin —
#   • the public landing / auth / settings site (tradexa-landing) at  "/"
#   • the session-gated trading dashboard (automation-hub-dashboard) at "/app"
# Build context is the repo ROOT.
#
# One image, three roles. HUB_ROLE (see automation-hub/ops/runtime.py) selects
# whether a container serves HTTP, runs the singleton trading workers, or both.
# Building one artifact and varying only configuration means the image that
# passed staging is byte-for-byte the image that reaches production.

# --- Stage 1: build the trading dashboard (served under /app) ---
FROM node:20.18-slim AS ui
WORKDIR /ui
COPY automation-hub-dashboard/package*.json ./
RUN npm ci
COPY automation-hub-dashboard/ ./
# base "/app/" so the dashboard's assets resolve while the landing owns "/assets"
ENV DASHBOARD_BASE=/app/
RUN npm run build          # -> /ui/dist

# --- Stage 2: build the landing / auth / settings site (served at /) ---
FROM node:20.18-slim AS landing
WORKDIR /landing
COPY tradexa-landing/package*.json ./
RUN npm ci
COPY tradexa-landing/ ./
# "Launch Bot" and post-login point at the dashboard on the same origin
ENV VITE_APP_URL=/app
RUN npm run build          # -> /landing/dist

# --- Stage 3: Python backend (serves both builds) ---
FROM python:3.11.11-slim

# Build metadata. Surfaced at /version and on the hub_build_info metric, so a
# dashboard can answer "which build produced this number" without cross-checking
# a deploy log.
ARG GIT_COMMIT=""
ARG APP_VERSION="0.0.0-dev"
ARG BUILD_DATE=""

LABEL org.opencontainers.image.title="Tradexa Automation Hub" \
      org.opencontainers.image.source="https://github.com/Arjuunb/Tradexa-Trading-Bot" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GIT_COMMIT=${GIT_COMMIT} \
    HUB_VERSION=${APP_VERSION}

WORKDIR /app

# Dependencies before source. The hub's requirements change rarely and its code
# changes every commit, so installing first lets a code-only rebuild reuse the
# cached dependency layer instead of reinstalling ccxt and the OpenTelemetry
# stack on every push.
COPY automation-hub/requirements.txt /tmp/hub-requirements.txt
RUN pip install --no-cache-dir -r /tmp/hub-requirements.txt

COPY . .

# --no-deps: every third-party requirement is installed above, and the root
# package is pure stdlib (pyproject dependencies = []). Editable, and therefore
# run AFTER the source is copied — setuptools resolves `packages.find` at
# install time, so installing against an empty directory records an empty
# package list and every `import tradexa` then fails at runtime in the
# container while still working under pytest. That exact bug has bitten this
# repo before; test_packaging.py guards it.
RUN pip install --no-cache-dir --no-deps -e .

# Bundle both React builds so the backend serves them on one origin.
COPY --from=ui /ui/dist /app/automation-hub/webui
COPY --from=landing /landing/dist /app/automation-hub/landing

# The autonomous engine starts streaming real paper trades on boot.
ENV HUB_AUTO_ENGINE=1 \
    HUB_ROLE=all \
    HUB_LOG_FORMAT=json \
    HUB_DATA_DIR=/data

# Non-root, no login shell, no home directory. State lives in /data, kept
# separate from the code in /app so the root filesystem can be mounted
# read-only (deploy/k8s/base sets readOnlyRootFilesystem: true): /data is then
# the only writable mount the process needs.
RUN groupadd --system --gid 10001 hub \
 && useradd --system --uid 10001 --gid hub --no-create-home --shell /usr/sbin/nologin hub \
 && mkdir -p /data \
 && chown -R hub:hub /data /app
USER 10001:10001

WORKDIR /app/automation-hub
EXPOSE 8000

# start-period covers the React-serving boot and the first engine cycle, so a
# slow cold start is not mistaken for a failure and restarted in a loop.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD ["python", "/app/automation-hub/ops/healthcheck.py"]

# Hosts (Render/Railway/Fly) inject $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
