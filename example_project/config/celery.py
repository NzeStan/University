import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("university_example")
app.config_from_object("django.conf:settings", namespace="CELERY")
# University modules register their tasks on app ready; the single generic
# task "university.core.run_task" dispatches them by name.
app.autodiscover_tasks(["university.core.integrations"], related_name="celery")
