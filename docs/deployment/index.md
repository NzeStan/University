# Deployment

## Production checklist

- [ ] `DEBUG = False`, explicit `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
- [ ] Merge `production_security_settings()` (HTTPS redirect, HSTS, secure/HttpOnly/SameSite cookies, `X-Frame-Options`).
- [ ] Dedicated secrets from the environment or a secret manager: `SECRET_KEY`, `UNIVERSITY["AUTH"]["JWT"]["SIGNING_KEY"]`, `UNIVERSITY["SECURITY"]["HMAC_KEY"]`.
- [ ] PostgreSQL with `CONN_MAX_AGE`/`CONN_HEALTH_CHECKS`, or PgBouncer.
- [ ] **Redis** cache (required for distributed rate limits, lockouts and permission caching).
- [ ] Celery workers + beat with `TASKS.BACKEND = CeleryTaskBackend` (schedule `university.core.purge`).
- [ ] Object storage for `default` and a separate **private** storage/bucket for sensitive uploads.
- [ ] Real email and SMS providers configured.
- [ ] `SECURITY.TRUSTED_PROXY_COUNT` matches your proxy/CDN topology.
- [ ] CORS limited to explicit origins (`CORS_ALLOWED_ORIGINS`); never allow all.
- [ ] Argon2 password hasher (`university-core[argon2]`).
- [ ] Structured logs (`logging_settings()`) shipped to your log platform; error tracking (e.g. Sentry) with PII scrubbing.
- [ ] Liveness probe `/health/live/`, readiness probe `/health/ready/`.
- [ ] `python manage.py check --deploy` passes with no University warnings.
- [ ] Database role for the app has `INSERT`/`SELECT` only on the audit table (recommended).
- [ ] Backups and restore drills; a retention schedule agreed with your data-protection officer.

## Reference topology

```text
            Clients (web, Android, iOS)
                       │  HTTPS
                 CDN / WAF / LB  ──────────── object storage (media, private bucket)
                       │
         ┌─────────────┼─────────────┐
     app server    app server    app server     (stateless: gunicorn/uvicorn)
         └─────────────┼─────────────┘
           ┌───────────┼────────────┬───────────────┐
      PostgreSQL     Redis      Celery workers    Celery beat
      (primary +   (cache,      (email, SMS,
       replicas)   throttle,     media, search)
                   broker)
```

The example project contains a Dockerfile (non-root user) and a Docker Compose stack with exactly
these roles.

## Observability

- **Request IDs**: every response has `X-Request-ID`, which is also included in log records
  (`RequestContextFilter`) and error bodies. Set `SECURITY.TRUST_INCOMING_REQUEST_ID` only behind
  an edge that generates them.
- **Logs**: JSON, one line per event, with secrets redacted (`RedactingFilter`).
- **Audit stream**: add `university.audit.sinks.LoggingSink` to forward audit entries.
- **Metrics**: export request latency and error rates from your server/APM. Useful
  University-level signals are `auth.login.failed` and `security.*` audit actions, plus the
  `security.login.suspicious` and `security.refresh_token.reused` events.
- **Health**: `/health/ready/` reports `{"database": "ok", "cache": "ok", …}` without
  infrastructure details, and returns `503` when a critical check fails.

## Scaling

University is built to scale horizontally. Capacity depends on infrastructure, not on a limit in
the code. Plan by tier and **measure** with load tests rather than assuming.

| Tier (registered users) | Typical setup | Watch for |
| --- | --- | --- |
| ~10k | 2 app instances, managed Postgres, single Redis, 1 worker | baseline latency, slow queries |
| ~100k | 3–6 app instances, Postgres with PgBouncer, Redis with persistence, 2–4 workers, CDN for media | connection limits, N+1 queries, cache hit rate |
| ~1M | autoscaled app tier, Postgres read replicas (route read-heavy selectors), Redis cluster or separate cache/broker instances, dedicated queues per workload | replica lag, hot rows, queue backlogs, index bloat |
| 10M+ | partitioning of high-volume tables (audit log, sessions, analytics events) by time, analytics/search in dedicated stores (OpenSearch, columnar), regional edge caching, consider UUIDv7 (`IDS.UUID_VERSION`) | write amplification, cross-region latency, data-residency requirements |

Design choices that keep this path open:

- No process-local state: throttles, lockouts and permission caches live in the shared cache.
- Access tokens are validated with **one indexed primary-key lookup** (session + user), and
  `last_seen_at` writes are throttled.
- Events dispatch after commit, and heavy work goes to the task queue.
- High-volume tables have composite indexes on their access patterns, and audit and analytics data
  are designed to be partitioned or moved out of the primary database.

### Load testing

`loadtests/locustfile.py` simulates realistic traffic: sign-in, token refresh, profile reads,
institution browsing and membership requests.

```bash
pip install locust
locust -f loadtests/locustfile.py --host https://staging.example.com
```

Run against an environment that mirrors production. Increase the user count step by step
(10k → 100k → 1M simulated sessions, scaled to your concurrency assumptions) and record p50/p95/p99
latency, error rates, database CPU and connection counts, Redis operations per second and queue
depth. Raise rate limits for the test accounts' IP ranges only within the staging environment.
