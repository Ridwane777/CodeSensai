"""Teste la politique « sans surveillance » des tâches planifiées — feature [X5].

Personne ne peut répondre « oui » à une confirmation : tout ce qui en demande
une doit être refusé, quelles que soient les préférences.
"""
from typing import ClassVar

from sensai.core.events import Done
from sensai.execution.gateway import deny_all
from sensai.execution.tool_policy import Mode, ToolPreferences
from sensai.scheduling.runner import build_unattended_gateway, unattended_preferences

from .helpers import add


def names(gateway):
    return {d["name"] for d in gateway.describe_all()}


def test_write_and_execute_tools_are_refused_and_never_run(registry):
    gateway = build_unattended_gateway(registry, ToolPreferences())
    for name in ("ecrire", "lancer"):
        result = gateway.call(name, text="x")
        assert not result.ok
        assert result.data["error"] == "refused"
        assert registry.get(name).calls == []


def test_allow_preference_cannot_loosen_write_or_execute(registry):
    prefs = ToolPreferences(modes={"ecrire": Mode.ALLOW, "lancer": Mode.ALLOW, "lire": Mode.ALLOW})
    gateway = build_unattended_gateway(registry, prefs)
    assert gateway.call("ecrire", text="x").data["error"] == "refused"
    assert gateway.call("lancer", text="x").data["error"] == "refused"
    assert registry.get("ecrire").calls == [] and registry.get("lancer").calls == []
    assert gateway.call("lire", text="x").ok  # lecture : autorisée


def test_gateway_confirmer_is_deny_all_and_not_replaceable_by_config(registry):
    gateway = build_unattended_gateway(registry, ToolPreferences(confirm_timeout_s=0.01))
    assert gateway.confirm is deny_all


def test_scheduled_run_never_executes_write_or_execute_even_with_allow(
    make_scheduler, registry
):
    def agent(host, model, messages, tools):
        tools.call("ecrire", text="x")
        tools.call("lancer", text="x")
        yield Done()

    prefs = ToolPreferences(modes={"ecrire": Mode.ALLOW, "lancer": Mode.ALLOW})
    s = make_scheduler(agent=agent, registry=registry, preferences=prefs)
    add(s, "a")
    record = s.run_due()[0]
    assert registry.get("ecrire").calls == [] and registry.get("lancer").calls == []
    assert record["tool_calls"] == [
        {"name": "ecrire", "ok": False, "error": "refused"},
        {"name": "lancer", "ok": False, "error": "refused"},
    ]


def test_read_and_network_tools_still_work_unattended(registry):
    gateway = build_unattended_gateway(registry, ToolPreferences())
    assert gateway.call("chercher", text="x").ok
    assert len(registry.get("chercher").calls) == 1


def test_after_reading_untrusted_content_network_tools_are_refused(registry):
    gateway = build_unattended_gateway(registry, ToolPreferences())
    assert gateway.call("lire", text="x").ok
    result = gateway.call("chercher", text="fuite")
    assert result.data["error"] == "refused"
    assert registry.get("chercher").calls == []


def test_confirm_after_untrusted_is_forced_even_if_config_says_false(registry):
    base = ToolPreferences(confirm_after_untrusted=False)
    assert unattended_preferences(base, registry, None).confirm_after_untrusted is True


def test_allowlist_hides_the_other_tools_from_the_model(registry):
    gateway = build_unattended_gateway(registry, ToolPreferences(), ["lire"])
    assert names(gateway) == {"lire"}
    result = gateway.call("chercher", text="x")
    assert result.data["error"] == "disabled"
    assert registry.get("chercher").calls == []


def test_no_allowlist_offers_every_tool_the_policy_does_not_deny(registry):
    gateway = build_unattended_gateway(registry, ToolPreferences())
    assert names(gateway) == {"lire", "chercher", "ecrire", "lancer"}


def test_allowlist_is_merged_with_tools_already_disabled(registry):
    base = ToolPreferences(disabled=frozenset({"lire"}))
    gateway = build_unattended_gateway(registry, base, ["lire", "chercher"])
    assert names(gateway) == {"chercher"}


def test_untrusted_state_does_not_leak_between_runs(make_scheduler, registry, clock):
    results = []

    def agent(host, model, messages, tools):
        results.append(tools.call("chercher", text="x").ok)
        tools.call("lire", text="x")
        yield Done()

    s = make_scheduler(agent=agent, registry=registry)
    add(s, "a", interval_s=60)
    s.run_due()
    clock.advance(minutes=2)
    s.run_due()
    assert results == [True, True]  # sinon la 2e exécution aurait hérité de la méfiance


def test_reset_untrusted_is_called_on_a_reused_gateway(make_scheduler, registry):
    shared = build_unattended_gateway(registry, ToolPreferences())
    shared.call("lire", text="x")  # le passe en « contenu non fiable lu »
    seen = []

    def agent(host, model, messages, tools):
        seen.append(tools.call("chercher", text="x").ok)
        yield Done()

    s = make_scheduler(agent=agent, gateway_factory=lambda task: shared)
    add(s, "a")
    s.run_due()
    assert seen == [True]


def test_per_task_allowlist_is_applied_by_the_default_factory(make_scheduler, registry):
    offered = []

    def agent(host, model, messages, tools):
        offered.append(names(tools.inner))
        yield Done()

    s = make_scheduler(agent=agent, registry=registry)
    add(s, "a", tools=["lire"])
    s.run_due()
    assert offered == [{"lire"}]


class OutilBavard:
    """Outil en lecture qui renvoie un secret, comme un fichier de config lu."""

    name = "bavard"
    description = "renvoie un secret"
    risk = "read"
    parameters: ClassVar[dict] = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs):
        from sensai.core.tools import ToolResult

        return ToolResult(ok=True, content='API_KEY = "sk-abcdef1234567890abcdef"')


def test_les_garde_fous_masquent_les_secrets_sans_surveillance(registry):
    """OUT-15 (EV4) vaut aussi pour les tâches planifiées : personne ne relit
    ce que l'outil renvoie avant qu'il parte au modèle et au compte rendu."""
    registry.register(OutilBavard())
    gateway = build_unattended_gateway(registry, ToolPreferences())

    result = gateway.call("bavard")

    assert result.ok
    assert "sk-abcdef1234567890abcdef" not in result.content
