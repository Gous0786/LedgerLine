# The backend, plus the built frontend so the container also works on its own.
# Deployed to Render (see render.yaml); runs anywhere:
#   docker build -t ledgerline . && docker run -p 7860:7860 \
#     -e OPENROUTER_API_KEY=... ledgerline

# --- frontend ---------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- backend ----------------------------------------------------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
RUN useradd -m -u 1000 user

WORKDIR /app
# Dependencies first, so a code change does not reinstall them.
COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-dev --no-cache

COPY backend/ backend/
COPY demo/data/ demo/data/
COPY --from=web /web/dist/ frontend/dist/
RUN chown -R user:user /app

USER user
WORKDIR /app/backend
# The database lives inside the container, so it starts fresh on every
# restart -- which is what a public demo wants.
ENV DEMO_MODE=true
EXPOSE 7860
# Hosts such as Render say which port to listen on through $PORT.
CMD ["sh", "-c", "exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
