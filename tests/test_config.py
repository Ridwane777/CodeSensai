"""
Teste la résolution des chemins de configuration.

Le test qui compte est `test_prompt_trouve_depuis_un_autre_dossier` : il échoue
si quelqu'un remet une lecture relative au dossier courant, ce qui ferait
démarrer l'agent sans prompt système dès qu'on le lance hors du dépôt.
"""
import json
import os

import pytest

from sensai.config import (
    get_settings,
    load_config_file,
    load_system_prompt,
    num_ctx_from_config,
    resolve_path,
)
from sensai.knowledge.compression import DEFAULT_NUM_CTX, budget_from_num_ctx
from sensai.knowledge.prompt_versions import PromptStore


def test_prompt_trouve_depuis_un_autre_dossier(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    assert get_settings()["system_prompt"] != ""
    assert load_config_file()["model"]


def test_prompts_lus_dans_la_version_active(tmp_path, monkeypatch):
    """A4 (ADR-0010) : l'agent lit la version qui porte le marque-page."""
    monkeypatch.chdir(tmp_path)
    store = PromptStore(tmp_path / "prompts")
    store.save("system", "Système v1", "initial", author="Alice")
    store.save("system", "Système v2", "suite", author="Alice")
    store.save("memory", "Mémoire v1", "initial", author="Alice")
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["system_prompt"] == "Système v1"
    assert settings["memory_prompt"] == "Mémoire v1"
    assert settings["prompt_versions"] == {"system": "v1", "memory": "v1"}

    store.use("system", "v2")
    assert get_settings()["system_prompt"] == "Système v2"


def test_brouillon_passe_en_option_prioritaire(tmp_path, monkeypatch):
    """Essayer un brouillon avant de le ranger : --system-prompt garde la main."""
    monkeypatch.chdir(tmp_path)
    store = PromptStore(tmp_path / "prompts")
    store.save("system", "Système rangé", "initial", author="Alice")
    store.save("memory", "Mémoire", "initial", author="Alice")
    (tmp_path / "brouillon.txt").write_text("Brouillon", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai", "--system-prompt", "brouillon.txt"])

    settings = get_settings()

    assert settings["system_prompt"] == "Brouillon"
    assert settings["prompt_versions"]["system"] == "brouillon.txt (non rangé)"
    assert settings["prompt_versions"]["memory"] == "v1"


def test_sans_registre_anciens_fichiers_relus(tmp_path, monkeypatch):
    """Repli tant que les autres branches n'ont pas fusionné A4."""
    racine = tmp_path / "depot"
    (racine / "prompts").mkdir(parents=True)
    (racine / "prompts" / "system_prompt.txt").write_text("Ancien système", encoding="utf-8")
    (racine / "prompts" / "memory_prompt.txt").write_text("Ancienne mémoire", encoding="utf-8")
    monkeypatch.setattr("sensai.config.PROJECT_ROOT", racine)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["system_prompt"] == "Ancien système"
    assert settings["memory_prompt"] == "Ancienne mémoire"
    assert settings["prompt_versions"] == {}


def test_consigne_de_reprise_chargee_depuis_un_fichier(tmp_path, monkeypatch):
    """Comme le prompt système : un fichier de prompts/, jamais une constante."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    assert "historique" in get_settings()["memory_prompt"]


def test_le_dossier_courant_est_prioritaire(tmp_path, monkeypatch):
    """Un config.json posé à côté du projet de l'utilisateur doit gagner."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text('{"model": "mistral"}', encoding="utf-8")

    assert load_config_file()["model"] == "mistral"


def test_fichier_absent_ne_leve_pas():
    assert resolve_path("nexiste_pas.txt") is None
    assert load_system_prompt("nexiste_pas.txt") == ""
    assert load_config_file("nexiste_pas.json") == {}


def test_chemin_absolu_respecte(tmp_path):
    fichier = tmp_path / "prompt.txt"
    fichier.write_text("  bonjour  ", encoding="utf-8")

    assert load_system_prompt(os.fspath(fichier)) == "bonjour"


def test_retention_par_defaut_et_configurable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])
    assert get_settings()["retention_days"] == 30

    (tmp_path / "config.json").write_text('{"retention_days": 90}', encoding="utf-8")
    assert get_settings()["retention_days"] == 90

    monkeypatch.setattr("sys.argv", ["sensai", "--retention-days", "0"])
    assert get_settings()["retention_days"] == 0


def test_retention_negative_refusee(tmp_path, monkeypatch):
    """Une durée négative purgerait tout : on refuse au lieu de deviner."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai", "--retention-days", "-1"])

    with pytest.raises(SystemExit):
        get_settings()


def test_reglages_du_rag_par_defaut(tmp_path, monkeypatch):
    """Valeurs tranchées par l'ADR-0009, mesurées dans docs/performance/R1-rag.md."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["rag"] is True
    assert settings["rag_model"] == "bge-m3"
    assert settings["rag_min_score"] == 0.54
    assert settings["rag_top_k"] == 5


def test_rag_desactivable_et_seuil_configurable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text('{"rag_min_score": 0.6}', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai", "--no-rag"])

    settings = get_settings()

    assert settings["rag"] is False
    assert settings["rag_min_score"] == 0.6


def test_seuil_hors_bornes_refuse(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai", "--rag-min-score", "1.5"])

    with pytest.raises(SystemExit):
        get_settings()


def test_reglages_des_outils_et_des_fichiers_lus(tmp_path, monkeypatch):
    """ADR-0011 et contrat des outils : les sections `tools` et `files` de
    config.json s'appliquent au CLI, pas seulement au planificateur."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(
        '{"tools": {"disabled": ["web_search"], "tool_timeout_s": 30},'
        ' "files": {"read": ["docs"], "write": ["docs"]}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["tool_preferences"].disabled == frozenset({"web_search"})
    assert settings["tool_preferences"].tool_timeout_s == 30
    assert settings["file_permissions"].read_roots == ((tmp_path / "docs").resolve(),)


def test_sans_section_les_reglages_par_defaut(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])

    settings = get_settings()

    assert settings["tool_preferences"].disabled == frozenset()
    assert settings["file_permissions"].read_roots == (tmp_path.resolve(),)


@pytest.mark.parametrize("section", ['"tools": {"dsabled": []}', '"files": {"reed": ["."]}'])
def test_faute_de_frappe_dans_la_config_refusee(tmp_path, monkeypatch, section):
    """Une restriction mal orthographiée ne doit pas être ignorée en silence :
    on croirait l'outil désactivé alors qu'il ne l'est pas."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text("{" + section + "}", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai"])

    with pytest.raises(SystemExit):
        get_settings()


@pytest.mark.parametrize("personas", [
    '"abc"',
    '{"profiles": ["x"]}',
    '{"profiles": [{"id": ["a"], "name": "n", "role": "r", "tone": "t", "scope": "s"}]}',
    '{"profiles": [{"id": "a", "name": 1, "role": "r", "tone": "t", "scope": "s"}]}',
    '{"profiles": [{"id": "a", "name": "", "role": "r", "tone": "t", "scope": "s"}]}',
    '{"profiles": [{"id": "a", "name": "n", "role": "r", "tone": "t", "scope": "s"}],'
    ' "default": "inconnue"}',
])
def test_persona_mal_ecrite_arrete_le_cli_avec_un_message(tmp_path, monkeypatch, capsys, personas):
    """Revue PR #94 : une section `personas` invalide donne un `parser.error`
    lisible (code 2), jamais une trace Python."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(
        '{"personas": ' + personas + "}", encoding="utf-8"
    )
    monkeypatch.setattr("sys.argv", ["sensai"])

    with pytest.raises(SystemExit) as sortie:
        get_settings()

    assert sortie.value.code == 2
    assert "config.json : personas" in capsys.readouterr().err


def _settings(tmp_path, monkeypatch, argv=(), config=None):
    monkeypatch.chdir(tmp_path)
    if config is not None:
        (tmp_path / "config.json").write_text(config, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai", *argv])
    return get_settings()


def test_num_ctx_et_budget_par_defaut(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    assert settings["num_ctx"] == DEFAULT_NUM_CTX
    assert settings["token_budget_max"] == budget_from_num_ctx(DEFAULT_NUM_CTX)


@pytest.mark.parametrize("num_ctx", [4096, 32768])
def test_le_budget_suit_le_num_ctx_de_la_ligne_de_commande(tmp_path, monkeypatch, num_ctx):
    """Revue PR #97 : `--num-ctx 4096` laissait le budget à 6192, plus grand que la
    fenêtre — Ollama tronquait avant que le résumé ne se déclenche."""
    settings = _settings(tmp_path, monkeypatch, ["--num-ctx", str(num_ctx)])
    assert settings["num_ctx"] == num_ctx
    assert settings["token_budget_max"] == budget_from_num_ctx(num_ctx)


def test_le_budget_suit_le_num_ctx_de_config_json(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch, config='{"num_ctx": 16384}')
    assert settings["token_budget_max"] == budget_from_num_ctx(16384)


def test_la_ligne_de_commande_l_emporte_sur_config_json_pour_num_ctx(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch, ["--num-ctx", "4096"], '{"num_ctx": 16384}')
    assert settings["token_budget_max"] == budget_from_num_ctx(4096)


def test_un_budget_explicite_n_est_pas_recalcule(tmp_path, monkeypatch):
    argv = ["--num-ctx", "32768", "--token-budget-max", "5000"]
    settings = _settings(tmp_path, monkeypatch, argv)
    assert settings["token_budget_max"] == 5000
    settings = _settings(tmp_path, monkeypatch, config='{"token_budget_max": 3000}')
    assert settings["token_budget_max"] == 3000


def test_un_budget_qui_depasse_la_fenetre_est_refuse(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _settings(tmp_path, monkeypatch, ["--num-ctx", "4096", "--token-budget-max", "5000"])
    assert "--token-budget-max" in capsys.readouterr().err


@pytest.mark.parametrize("valeur", ["0", '"8192"', "true", "1.5"])
def test_num_ctx_invalide_dans_config_json_refuse(valeur):
    with pytest.raises(ValueError, match="num_ctx"):
        num_ctx_from_config({"num_ctx": json.loads(valeur)})


def test_num_ctx_par_defaut_pour_schedule_et_eval():
    assert num_ctx_from_config({}) == DEFAULT_NUM_CTX
    assert num_ctx_from_config({"num_ctx": 4096}) == 4096


# --- Paramètres de génération et nombre d'étapes (ADR-0057) ------------------------

def test_parametres_de_generation_par_defaut_et_surcharges(tmp_path, monkeypatch):
    """Les paramètres de génération passent par la configuration."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text(
        json.dumps({"generation": {"temperature": 0.5, "seed": 42}, "max_iterations": 9}),
        encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai", "--top-p", "0.8"])
    settings = get_settings()
    assert settings["generation"] == {"temperature": 0.5, "top_p": 0.8, "seed": 42}
    assert settings["max_iterations"] == 9


def test_parametre_de_generation_inconnu_refuse(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.json").write_text('{"generation": {"temprature": 0.1}}', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["sensai"])
    with pytest.raises(SystemExit):
        get_settings()


def test_lecteurs_pour_schedule_et_eval():
    from sensai.config import DEFAULT_GENERATION, generation_from_config, max_iterations_from_config

    assert generation_from_config({}) == DEFAULT_GENERATION
    assert generation_from_config({"generation": {"temperature": 0}})["temperature"] == 0
    assert max_iterations_from_config({}) == 6
    with pytest.raises(ValueError):
        generation_from_config({"generation": {"temp": 1}})
    with pytest.raises(ValueError):
        max_iterations_from_config({"max_iterations": 0})


def test_le_cache_est_desactive_par_defaut(tmp_path, monkeypatch):
    """ADR-0056 : A6 devient optionnel (`--cache` ou "cache": true)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["sensai"])
    assert get_settings()["cache"] is False
    monkeypatch.setattr("sys.argv", ["sensai", "--cache"])
    assert get_settings()["cache"] is True
