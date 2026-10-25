# Example project

Shows how a consumer composes **University Core** with optional modules. Configuration comes from
environment variables (`.env.example`), and nothing secret is committed.

## Run locally (SQLite, no services)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=true
python manage.py migrate
python manage.py university_import_institutions data/institutions.sample.json
python manage.py createsuperuser
python manage.py runserver
```

Open http://localhost:8000/api/docs/ for the interactive API, or http://localhost:8000/admin/.

## Run the full stack (PostgreSQL, Redis, Celery)

```bash
cp .env.example .env        # then edit secrets
docker compose up --build   # api on :8000, worker, beat, db, redis
```

## What to look at

- `config/settings.py`: `INSTALLED_APPS` composed from `CORE_APPS` plus optional modules;
  `UNIVERSITY` settings; providers; Celery; production security settings.
- `config/urls.py`: a single `include("university.core.urls")` mounts health checks, the
  versioned API of every installed module and the OpenAPI docs.
- `data/institutions.sample.json`: illustrative (fictional) institutions across Nigeria, Ghana
  and Kenya.
