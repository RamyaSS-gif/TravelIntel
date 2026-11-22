# Stage 1: build the React frontend
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python API that also serves the built frontend
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    TRAVELINTEL_DB_PATH=/data/travelintel_warehouse.db
COPY config.py ./
COPY olap/ ./olap/
COPY deploy/ ./deploy/
COPY --from=frontend /app/frontend/dist ./frontend/dist

# The database is downloaded on start into TRAVELINTEL_DB_PATH (skipped if present)
CMD ["sh", "-c", "python deploy/fetch_database.py && python -m olap.api_server"]
