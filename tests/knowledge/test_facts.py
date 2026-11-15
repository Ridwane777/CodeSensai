"""
Tests the structured fact memory - feature [M3], ADR-0030.

`test_a_fact_survives_a_new_instance` carries the M3 promise ("over time");
`test_memory_is_specific_to_the_project` guards US-M3-3.
"""
import pytest

from sensai.knowledge.facts import MAX_PROMPT_ENTITIES, FactError, FactStore


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data" / "memory.db"


@pytest.fixture
def facts(db):
    return FactStore(db, project="/projects/demo")


# --- US-M3-1: remember, without duplicates, over time ----------------------------


def test_remember_then_recall(facts):
    result = facts.remember("auth", "redis_version", "7")

    assert result["change"] == "created"
    assert facts.recall(entity="auth") == [
        {"entity": "auth", "attribute": "redis_version", "value": "7",
         "updated_at": facts.recall(entity="auth")[0]["updated_at"]}
    ]


def test_a_fact_survives_a_new_instance(db):
    FactStore(db, project="/p").remember("auth", "redis_version", "7")

    assert FactStore(db, project="/p").recall(entity="auth")[0]["value"] == "7"


def test_no_duplicate_names_compared_ignoring_case_and_spaces(facts):
    facts.remember("auth", "redis_version", "7")

    result = facts.remember(" Auth ", "Redis_Version", "7")

    assert result["change"] == "unchanged"
    assert len(facts.recall(entity="AUTH")) == 1


def test_replace_replaces_the_value(facts):
    facts.remember("auth", "redis_version", "7")

    result = facts.remember("auth", "redis_version", "8")

    assert result["change"] == "updated"
    assert result["old_values"] == ["7"]
    assert [f["value"] for f in facts.recall(entity="auth")] == ["8"]


def test_add_adds_one_more_value(facts):
    facts.remember("auth", "depends_on", "redis", mode="add")
    facts.remember("auth", "depends_on", "postgres", mode="add")

    values = sorted(f["value"] for f in facts.recall(entity="auth", attribute="depends_on"))
    assert values == ["postgres", "redis"]


@pytest.mark.parametrize(
    ("entity", "attribute", "value", "mode"),
    [("", "a", "v", "replace"), ("e", "  ", "v", "replace"), ("e", "a", "", "replace"),
     ("e", "a", "v", "delete"), ("e" * 101, "a", "v", "replace"), ("e", "a", "v" * 501, "add")],
)
def test_invalid_facts_rejected(facts, entity, attribute, value, mode):
    with pytest.raises(FactError):
        facts.remember(entity, attribute, value, mode=mode)

    assert facts.entities() == []


# --- US-M3-2: recall, in both directions -----------------------------------------


def test_inverse_relations(facts):
    facts.remember("auth", "depends_on", "redis", mode="add")
    facts.remember("cache", "depends_on", "Redis", mode="add")
    facts.remember("billing", "depends_on", "postgres", mode="add")

    entities = sorted(f["entity"] for f in facts.recall(value="redis"))
    assert entities == ["auth", "cache"]


def test_search_without_result(facts):
    assert facts.recall(entity="unknown") == []


def test_search_without_criteria_rejected(facts):
    with pytest.raises(FactError):
        facts.recall()


# --- US-M3-3: correct, forget, history, per project ------------------------------


def test_the_old_value_stays_in_history(facts):
    facts.remember("auth", "redis_version", "7")
    facts.remember("auth", "redis_version", "8")

    history = facts.history("auth")

    assert history[0]["action"] == "replace"
    assert history[0]["old_value"] == "7"
    assert history[0]["new_value"] == "8"


def test_forget_one_specific_fact(facts):
    facts.remember("auth", "depends_on", "redis", mode="add")
    facts.remember("auth", "depends_on", "postgres", mode="add")

    assert facts.forget("auth", "depends_on", "redis") == 1

    assert [f["value"] for f in facts.recall(entity="auth")] == ["postgres"]
    assert facts.history("auth")[0]["action"] == "forget"


def test_forget_a_whole_entity(facts):
    facts.remember("auth", "redis_version", "7")
    facts.remember("auth", "owner", "Alice")

    assert facts.forget("auth") == 2
    assert facts.recall(entity="auth") == []


def test_memory_is_specific_to_the_project(db):
    FactStore(db, project="/project-a").remember("auth", "redis_version", "7")

    assert FactStore(db, project="/project-b").recall(entity="auth") == []


def test_file_readable_by_owner_only(facts, db):
    facts.remember("auth", "redis_version", "7")

    assert db.stat().st_mode & 0o777 == 0o600
    assert db.parent.stat().st_mode & 0o777 == 0o700


# --- System prompt (ADR-0030, decision 3) -----------------------------------------


def test_no_fact_no_prompt(facts):
    assert facts.as_prompt() == ""


def test_the_prompt_lists_entities_not_facts(facts):
    facts.remember("auth", "redis_version", "7")
    facts.remember("sandbox", "owner", "Alice")

    prompt = facts.as_prompt()

    assert "auth" in prompt and "sandbox" in prompt
    assert "Alice" not in prompt
    assert "recall_facts" in prompt
    assert "data" in prompt.lower()


def test_the_prompt_is_capped(facts):
    for i in range(MAX_PROMPT_ENTITIES + 5):
        facts.remember(f"service{i}", "port", str(8000 + i))

    prompt = facts.as_prompt()

    assert prompt.count("service") <= MAX_PROMPT_ENTITIES + 1
    assert "others" in prompt


def test_preview_shows_old_and_new_value(facts):
    facts.remember("auth", "redis_version", "7")

    preview = facts.preview("auth", "redis_version", "8")

    assert "7" in preview and "8" in preview
    assert [f["value"] for f in facts.recall(entity="auth")] == ["7"]


def test_history_distinguishes_creation_addition_and_replacement(facts):
    """Real trial run of 2026-10-17: a newly created fact showed up as "replace"."""
    facts.remember("auth", "redis_version", "7")
    facts.remember("auth", "depends_on", "redis", mode="add")
    facts.remember("auth", "depends_on", "postgres", mode="add")
    facts.remember("auth", "redis_version", "8")

    actions = [(h["attribute"], h["action"]) for h in reversed(facts.history("auth"))]

    assert actions == [("redis_version", "create"), ("depends_on", "create"),
                       ("depends_on", "add"), ("redis_version", "replace")]


# --- Name consistency (real trial run of 2026-10-17: "version redis" and
# "redis_version" stored next to the old fact instead of replacing it)


def test_spaces_hyphens_and_underscores_mean_the_same_attribute(facts):
    facts.remember("auth", "redis version", "7")

    result = facts.remember("Auth", "Redis-Version", "8")

    assert result["change"] == "updated"
    assert [f["value"] for f in facts.recall(entity="auth")] == ["8"]
    assert facts.recall(entity="auth", attribute="redis_version")[0]["value"] == "8"


def test_the_result_lists_the_other_attributes_of_the_entity(facts):
    facts.remember("auth", "uses_redis", "7")
    facts.remember("auth", "port", "8080")

    result = facts.remember("auth", "redis_version", "8")

    assert ("uses_redis", ["7"]) in result["others"]
    assert ("port", ["8080"]) in result["others"]


def test_the_preview_shows_existing_attributes_to_spot_a_duplicate(facts):
    facts.remember("auth", "uses_redis", "7")

    preview = facts.preview("auth", "redis_version", "8")

    assert "uses_redis" in preview and "7" in preview


def test_the_preview_of_a_new_entity_shows_known_entities(facts):
    facts.remember("auth service", "port", "8080")

    preview = facts.preview("auth", "port", "9090")

    assert "auth service" in preview


def test_the_prompt_asks_to_check_before_saving(facts):
    facts.remember("auth", "port", "8080")

    assert "before" in facts.as_prompt().lower() and "recall_facts" in facts.as_prompt()
