from __future__ import annotations

from university.core.tasks import task

CALLS: list[tuple[str, int]] = []


@task(name="testapp.record")
def record_call(label: str, value: int = 0) -> None:
    CALLS.append((label, value))
