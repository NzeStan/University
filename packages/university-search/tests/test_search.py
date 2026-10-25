from __future__ import annotations

import pytest

from tests.audience.apps import MEMBERS
from tests.content.apps import BLOCKS, ITEMS
from university.core.events import publish
from university.core.testing import create_user
from university.search.models import SearchEntry

pytestmark = pytest.mark.django_db
BASE = "/api/v1/search"
INST = "11111111-1111-4111-8111-111111111111"


def save(key, **item):
    ITEMS[key] = {"author": item.pop("author", "a1"), **item}
    publish("test.item.saved", {"item_id": key})


def search(client, q, **params):
    return client.get(f"{BASE}/", {"q": q, **params})


def ids(response):
    return [r["object_id"] for r in response.json()]


def test_indexing_and_search(api_client):
    save("i1", label="Exam timetable for 300 level\nComputer science department")
    save("i2", label="Football match tonight")
    assert SearchEntry.objects.get(object_id="i1").tags == " public "
    result = search(api_client, "exam timetable").json()
    assert [r["object_id"] for r in result] == ["i1"]
    assert (
        result[0]["title"] == "Exam timetable for 300 level" and result[0]["snippet"] == "Computer science department"
    )
    assert ids(search(api_client, "football", types="test.item")) == ["i2"]
    assert ids(search(api_client, "football", types="nope.type")) == ["i2"]  # Unknown types are ignored.
    publish("test.item.removed", {"item_id": "i2"})
    assert ids(search(api_client, "football")) == []


@pytest.mark.security
def test_results_are_checked_against_the_viewer(api_client, auth_client, user, other_user):
    save("public", label="Hostel meeting notes")
    save("scoped", label="Hostel meeting for members", scope=("institution", INST))
    ITEMS["scoped"]["hidden_from"] = {"", str(other_user.pk)}  # Anonymous visitors and Grace can't see it.
    publish("test.item.saved", {"item_id": "scoped"})
    assert SearchEntry.objects.get(object_id="scoped").tags == f" institution:{INST} "
    assert ids(search(api_client, "hostel meeting")) == ["public"]
    MEMBERS[str(user.pk)] = [("institution", INST)]
    MEMBERS[str(other_user.pk)] = [("institution", INST)]
    assert set(ids(search(auth_client(user), "hostel meeting"))) == {"public", "scoped"}
    # Grace carries the tag, but the adapter (e.g. a block or a removal) says no: not returned.
    assert ids(search(auth_client(other_user), "hostel meeting")) == ["public"]


@pytest.mark.security
def test_hidden_items_are_never_returned(api_client):
    save("draft", label="Secret launch plan", hidden_from={""})
    assert SearchEntry.objects.get(object_id="draft").tags == " restricted "
    assert ids(search(api_client, "secret launch")) == []


@pytest.mark.security
def test_query_validation_is_generic(api_client):
    assert search(api_client, "a").status_code == 400
    assert search(api_client, "x" * 101).status_code == 400
    assert search(api_client, "   ").json()["error"]["code"] == "invalid_query"


def test_reindex_backfills(api_client):
    from university.search.indexing import reindex

    ITEMS["late"] = {"author": "a", "label": "Imported before search was installed"}
    assert ids(search(api_client, "imported")) == []
    assert reindex(["test.item"]) == 1
    assert ids(search(api_client, "imported")) == ["late"]


def test_purge_removes_a_persons_content_from_the_index(user):
    from university.core.hooks import Hook, hooks

    save("mine", label="My essay", author=str(user.pk))
    save("anon", label="Anonymous confession", author=None)
    assert SearchEntry.objects.get(object_id="anon").author_id == ""  # Never linked to anyone.
    hooks.call(Hook.USER_PURGE, user.pk)
    assert list(SearchEntry.objects.values_list("object_id", flat=True)) == ["anon"]


# ------------------------------------------------------------- people
@pytest.mark.security
def test_people_search_resists_enumeration(api_client, auth_client, user, other_user):
    from university.users.services.preferences import get_privacy_settings

    other_user.display_name = "Grace Hopper"
    other_user.save()
    hidden = create_user("hidden@example.com", handle="gracehidden")
    privacy = get_privacy_settings(hidden)
    privacy.searchable = False
    privacy.save()
    members_only = create_user("members@example.com", handle="gracemembers")
    privacy = get_privacy_settings(members_only)
    privacy.profile_visibility = "members"
    privacy.save()
    people = lambda client, q: [p["handle"] for p in client.get(f"{BASE}/people/", {"q": q}).json()]  # noqa: E731
    assert people(api_client, "grace") == ["grace"]  # Not the unsearchable or members-only profiles.
    assert set(people(auth_client(user), "grace")) == {"grace", "gracemembers"}
    assert people(api_client, "hopper") == ["grace"]
    assert people(api_client, "grace@example.com") == []  # Emails are never searchable.
    assert people(api_client, "example.com") == []
    assert api_client.get(f"{BASE}/people/", {"q": "gr"}).status_code == 400  # Too short to sweep.
    BLOCKS.add((str(other_user.pk), str(user.pk)))
    from university.core.hooks import Hook, hooks

    def blocked(viewer, target):
        return False if viewer and str(viewer.pk) == str(user.pk) and target.pk == other_user.pk else None

    hooks.register(Hook.USER_CAN_VIEW_PROFILE, blocked)
    try:
        assert "grace" not in people(auth_client(user), "grace")
    finally:
        hooks.unregister(Hook.USER_CAN_VIEW_PROFILE, blocked)
    assert "email" not in str(api_client.get(f"{BASE}/people/", {"q": "grace"}).json())


def test_types_endpoint(api_client):
    assert api_client.get(f"{BASE}/types/").json() == ["test.item"]


# ----------------------------------------------------------- opensearch
def test_opensearch_backend(monkeypatch):
    from university.core.exceptions import ProviderError
    from university.core.providers.search import SearchDocument, SearchQuery
    from university.search import backends

    calls = []

    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "DELETE" and url.endswith("/gone"):
            raise ProviderError(code="provider_http_error", details={"status": 404})
        if url.endswith("/_search"):
            return {"hits": {"hits": [{"_id": "p1", "_score": 2.5, "_source": {"content_type": "social.post"}}]}}
        return {"result": "ok"}

    monkeypatch.setattr(backends, "request", fake)
    backend = backends.OpenSearchBackend(url="https://search.internal:9200", api_key="k3y")
    backend.index(
        [SearchDocument(index="social.post", id="p1", body={"title": "T", "body": "B"}, visibility=["public"])]
    )
    method, url, kwargs = calls[-1]
    assert method == "PUT" and url == "https://search.internal:9200/university-social_post/_doc/p1"
    assert kwargs["json_body"]["tags"] == ["public"] and kwargs["headers"]["Authorization"] == "ApiKey k3y"
    hits = backend.search(
        SearchQuery(index="", text="exam", filters={"types": ["social.post"]}, visibility=["public", "institution:x"])
    )
    assert hits[0].id == "p1" and hits[0].index == "social.post"
    query = calls[-1][2]["json_body"]["query"]["bool"]
    assert {"terms": {"tags": ["public", "institution:x"]}} in query["filter"]
    assert {"terms": {"content_type": ["social.post"]}} in query["filter"]
    backend.delete("social.post", ["gone"])  # 404s are fine.
    backend.delete_by_author("u1")
    assert calls[-1][1].endswith("/university-*/_delete_by_query")


@pytest.mark.security
def test_email_shaped_queries_find_nobody(api_client):
    # Even when someone puts an email address in their display name.
    careless = create_user("careless@example.com", handle="careless")
    careless.display_name = "Write to careless@example.com"
    careless.save()
    assert api_client.get(f"{BASE}/people/", {"q": "careless@example.com"}).json() == []
    assert [p["handle"] for p in api_client.get(f"{BASE}/people/", {"q": "careless"}).json()] == ["careless"]
