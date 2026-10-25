"""Load-test scenarios for a University deployment (https://locust.io).

    pip install locust
    LOADTEST_PASSWORD=... locust -f loadtests/locustfile.py --host https://staging.example.com

Prerequisite: pre-create active test users ``loadtest+<n>@example.com`` (n = 0..N-1) sharing
LOADTEST_PASSWORD, for example with a management command in your staging environment. Only run
against environments you own; raise rate limits for the load generator in staging only.
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

PASSWORD = os.environ.get("LOADTEST_PASSWORD", "change-me")
USERS = int(os.environ.get("LOADTEST_USERS", "1000"))


class CampusUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self) -> None:
        self.email = f"loadtest+{random.randrange(USERS)}@example.com"  # noqa: S311 - not security sensitive
        self.login()
        self.institution_ids: list[str] = []

    def login(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login/", json={"identifier": self.email, "password": PASSWORD}, name="auth: login"
        )
        if response.status_code == 200:
            tokens = response.json()
            self.refresh = tokens["refresh"]
            self.client.headers["Authorization"] = f"Bearer {tokens['access']}"

    @task(10)
    def me(self) -> None:
        response = self.client.get("/api/v1/me/", name="me")
        if response.status_code == 401:
            self.refresh_tokens()

    @task(8)
    def browse_institutions(self) -> None:
        response = self.client.get("/api/v1/institutions/?country=NG", name="institutions: list")
        if response.ok:
            self.institution_ids = [i["id"] for i in response.json().get("results", [])]

    @task(4)
    def institution_detail(self) -> None:
        if self.institution_ids:
            institution = random.choice(self.institution_ids)  # noqa: S311
            self.client.get(f"/api/v1/institutions/{institution}/", name="institutions: detail")
            self.client.get(f"/api/v1/institutions/{institution}/units/", name="institutions: units")

    @task(3)
    def my_memberships(self) -> None:
        self.client.get("/api/v1/me/memberships/", name="memberships: mine")

    @task(2)
    def sessions(self) -> None:
        self.client.get("/api/v1/me/sessions/", name="sessions: list")

    @task(1)
    def refresh_tokens(self) -> None:
        if not getattr(self, "refresh", None):
            return
        response = self.client.post("/api/v1/auth/token/refresh/", json={"refresh": self.refresh}, name="auth: refresh")
        if response.status_code == 200:
            tokens = response.json()
            self.refresh = tokens["refresh"]
            self.client.headers["Authorization"] = f"Bearer {tokens['access']}"
        else:
            self.login()


class AnonymousVisitor(HttpUser):
    wait_time = between(2, 8)
    weight = 1

    @task
    def public_pages(self) -> None:
        self.client.get("/api/v1/institutions/", name="public: institutions")
        self.client.get("/api/v1/institution-types/", name="public: types")
        self.client.get("/health/live/", name="health: live")
