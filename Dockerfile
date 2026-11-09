FROM node:22-bookworm-slim AS frontend
WORKDIR /web
RUN npm install -g pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --node-linker=hoisted
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/public ./public
COPY frontend/src ./src
RUN pnpm run build

FROM python:3.12-slim-bookworm AS backend
ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision=$VCS_REF
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
RUN pip install --no-cache-dir --no-deps /app/backend
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/alembic /app/backend/alembic
COPY config /app/config
COPY --from=frontend /web/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 radar && chown -R radar:radar /app
USER radar
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
