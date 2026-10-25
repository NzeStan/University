# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Build from the repository root: docker build -f example_project/Dockerfile .
COPY packages /packages
COPY example_project/requirements.txt /app/requirements.txt
RUN sed -i 's#\.\./packages#/packages#g' requirements.txt \
    && pip install -r requirements.txt

COPY example_project /app

# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--access-logfile", "-"]
