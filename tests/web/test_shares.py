"""
Share links (X3, ADR-0048): the public page, what it shows and what
it never shows.

The test that matters: `test_the_link_opens_a_filtered_copy_without_an_api_token`
(US-X3-2: view a shared conversation in the browser).
"""
import json
from datetime import UTC, datetime, timedelta

import requests

from sensai.core.events import Done, Token
from sensai.web.shares import ShareStore

SECRET = "AKIAIOSFODNN7EXAMPLE"


def _conversation(env, question="Hello"):
    session_id = env.session()
    env.stream(session_id, question)
    return session_id


def _share(env, session_id):
    response = env.post(f"/api/sessions/{session_id}/share")
    assert response.status_code == 201, response.text
    return response.json()


def test_the_link_opens_a_filtered_copy_without_an_api_token(env):
    env.script.steps = [Token(f"Here is the key {SECRET}."), Done("final_answer")]
    shared = _share(env, _conversation(env, "Show <script>alert(1)</script>"))
    assert shared["url"] == f"/share/{shared['token']}"
    page = requests.get(env.base + shared["url"], timeout=5)  # no authentication header
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "Hello" not in page.text and "Show" in page.text
    assert "<script>" not in page.text and "&lt;script&gt;" in page.text
    assert SECRET not in page.text


def test_the_public_page_runs_nothing_and_is_not_indexed(env):
    page = requests.get(env.base + _share(env, _conversation(env))["url"], timeout=5)
    csp = page.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["cache-control"] == "no-store"


def test_it_is_a_snapshot(env):
    session_id = _conversation(env, "first")
    url = _share(env, session_id)["url"]
    env.stream(session_id, "said after sharing")
    assert "said after sharing" not in requests.get(env.base + url, timeout=5).text


def test_revoking_closes_the_link(env):
    shared = _share(env, _conversation(env))
    assert env.post(f"/api/shares/{shared['token']}/revoke").status_code == 204
    assert requests.get(env.base + shared["url"], timeout=5).status_code == 404
    assert env.post(f"/api/shares/{shared['token']}/revoke").status_code == 404


def test_an_unknown_link_gives_the_same_page_as_a_revoked_link(env):
    page = requests.get(f"{env.base}/share/unknown", timeout=5)
    assert page.status_code == 404 and "Link unavailable" in page.text


def test_an_empty_conversation_cannot_be_shared(env):
    response = env.post(f"/api/sessions/{env.session()}/share")
    assert response.status_code == 400 and response.json()["code"] == "EMPTY_SESSION"


def test_the_file_does_not_contain_the_token(env):
    shared = _share(env, _conversation(env))
    stored = env.runtime.shares.path.read_text(encoding="utf-8")
    assert shared["token"] not in stored
    assert oct(env.runtime.shares.path.stat().st_mode)[-3:] == "600"


def test_an_expired_link_is_no_longer_served_and_gets_purged(tmp_path):
    store = ShareStore(tmp_path / "shares.json")
    token = store.create("s1", [{"role": "user", "content": "a"}])["token"]
    data = json.loads(store.path.read_text())
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    for entry in data.values():
        entry["expires_at"] = past
    store.path.write_text(json.dumps(data))
    assert store.get(token) is None
    assert store.purge() == 1 and json.loads(store.path.read_text()) == {}


def test_only_conversation_messages_are_published(tmp_path):
    store = ShareStore(tmp_path / "shares.json")
    token = store.create("s1", [{"role": "system", "content": "prompt"},
                                {"role": "tool", "content": "output"},
                                {"role": "user", "content": "q"}])["token"]
    assert store.get(token)["messages"] == [{"role": "user", "content": "q"}]


def test_share_links_are_disabled_by_default(make_env):
    """ADR-0056: without `share_links: true` in config.json, no public link."""
    env = make_env(share_links=False)
    session_id = _conversation(env)
    response = env.post(f"/api/sessions/{session_id}/share")
    assert response.status_code == 403
    assert response.json()["code"] == "SHARE_DISABLED"


def test_the_share_links_setting_is_false_by_default(tmp_path, monkeypatch):
    from sensai.config import get_settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])
    assert get_settings()["share_links"] is False
    (tmp_path / "config.json").write_text('{"share_links": true}', encoding="utf-8")
    assert get_settings()["share_links"] is True
