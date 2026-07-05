# --- Frontend build ---
FROM node:20-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- API + static ---
FROM python:3.12-slim
WORKDIR /app/backend
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIST=/app/static

COPY backend/requirements.txt .
COPY backend/docker/fonts-local.conf /etc/fonts/local.conf
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        antiword \
        libreoffice-writer \
        libreoffice-core \
        fontconfig \
        fonts-liberation \
        fonts-dejavu-core \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

ENV DOCX_PDF_CONVERTER=libreoffice \
    HOME=/tmp

COPY backend/app ./app
COPY --from=frontend-build /src/frontend/dist /app/static

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
