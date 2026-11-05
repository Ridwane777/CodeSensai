"""
Liens de partage (X3, ADR-0048) : la page publique, ce qu'elle montre et ce
qu'elle ne montre jamais.

Le test qui compte : `test_le_lien_ouvre_une_copie_filtree_sans_jeton_d_api`
(US-X3-2 : consulter une conversation partagée dans le navigateur).
"""
import json
from datetime import UTC, datetime, timedelta

import requests

from sensai.core.events import Done, Token
from sensai.web.shares import ShareStore

SECRET = "AKIAIOSFODNN7EXAMPLE"


def _conversation(env, question="Bonjour"):
    session_id = env.session()
    env.stream(session_id, question)
    return session_id


def _share(env, session_id):
    response = env.post(f"/api/sessions/{session_id}/share")
    assert response.status_code == 201, response.text
    return response.json()


def test_le_lien_ouvre_une_copie_filtree_sans_jeton_d_api(env):
    env.script.steps = [Token(f"Voici la clé {SECRET}."), Done("final_answer")]
    shared = _share(env, _conversation(env, "Montre <script>alert(1)</script>"))
    assert shared["url"] == f"/share/{shared['token']}"
    page = requests.get(env.base + shared["url"], timeout=5)  # aucun en-tête d'authentification
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "Bonjour" not in page.text and "Montre" in page.text
    assert "<script>" not in page.text and "&lt;script&gt;" in page.text
    assert SECRET not in page.text


def test_la_page_publique_n_execute_rien_et_n_est_pas_indexee(env):
    page = requests.get(env.base + _share(env, _conversation(env))["url"], timeout=5)
    csp = page.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src" not in csp
    assert page.headers["x-robots-tag"] == "noindex, nofollow"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert page.headers["cache-control"] == "no-store"


def test_c_est_un_instantane(env):
    session_id = _conversation(env, "première")
    url = _share(env, session_id)["url"]
    env.stream(session_id, "dite après le partage")
    assert "dite après le partage" not in requests.get(env.base + url, timeout=5).text


def test_revoquer_ferme_le_lien(env):
    shared = _share(env, _conversation(env))
    assert env.post(f"/api/shares/{shared['token']}/revoke").status_code == 204
    assert requests.get(env.base + shared["url"], timeout=5).status_code == 404
    assert env.post(f"/api/shares/{shared['token']}/revoke").status_code == 404


def test_un_lien_inconnu_donne_la_meme_page_qu_un_lien_revoque(env):
    page = requests.get(f"{env.base}/share/inconnu", timeout=5)
    assert page.status_code == 404 and "Lien indisponible" in page.text


def test_une_conversation_vide_ne_se_partage_pas(env):
    response = env.post(f"/api/sessions/{env.session()}/share")
    assert response.status_code == 400 and response.json()["code"] == "EMPTY_SESSION"


def test_le_fichier_ne_contient_pas_le_jeton(env):
    shared = _share(env, _conversation(env))
    stored = env.runtime.shares.path.read_text(encoding="utf-8")
    assert shared["token"] not in stored
    assert oct(env.runtime.shares.path.stat().st_mode)[-3:] == "600"


def test_un_lien_expire_n_est_plus_servi_et_part_a_la_purge(tmp_path):
    store = ShareStore(tmp_path / "shares.json")
    token = store.create("s1", [{"role": "user", "content": "a"}])["token"]
    data = json.loads(store.path.read_text())
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    for entry in data.values():
        entry["expires_at"] = past
    store.path.write_text(json.dumps(data))
    assert store.get(token) is None
    assert store.purge() == 1 and json.loads(store.path.read_text()) == {}


def test_seuls_les_messages_de_la_conversation_sont_publies(tmp_path):
    store = ShareStore(tmp_path / "shares.json")
    token = store.create("s1", [{"role": "system", "content": "prompt"},
                                {"role": "tool", "content": "sortie"},
                                {"role": "user", "content": "q"}])["token"]
    assert store.get(token)["messages"] == [{"role": "user", "content": "q"}]


def test_les_liens_de_partage_sont_desactives_par_defaut(make_env):
    """ADR-0056 : sans `share_links: true` dans config.json, aucun lien public."""
    env = make_env(share_links=False)
    session_id = _conversation(env)
    response = env.post(f"/api/sessions/{session_id}/share")
    assert response.status_code == 403
    assert response.json()["code"] == "SHARE_DISABLED"


def test_le_reglage_share_links_est_faux_par_defaut(tmp_path, monkeypatch):
    from sensai.config import get_settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])
    assert get_settings()["share_links"] is False
    (tmp_path / "config.json").write_text('{"share_links": true}', encoding="utf-8")
    assert get_settings()["share_links"] is True
