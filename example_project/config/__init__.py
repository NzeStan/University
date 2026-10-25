try:  # Celery is optional
    from config.celery import app as celery_app
except ImportError:  # pragma: no cover
    celery_app = None

__all__ = ["celery_app"]
