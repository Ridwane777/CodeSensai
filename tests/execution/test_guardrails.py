"""Tests for the EV2 guardrails: what must be masked, and what must be left alone."""
import pytest

from sensai.execution.guardrails import check_input, filter_output, mask_pii, mask_secrets


@pytest.mark.parametrize(
    ("secret", "kind"),
    [
        ("sk-abcdefghijklmnop1234", "api_key"),
        ("sk-ant-api03-abcdefghijklmnop1234", "anthropic_key"),
        ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
        ("ghp_" + "a1B2c3D4e5" * 4, "github_token"),
        ("xoxb-123456789012-abcdefghij", "slack_token"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk", "jwt"),
        ("Bearer abcdefghijklmnopqrstuvwxyz", "bearer_token"),
    ],
)
def test_known_credentials_are_masked(secret, kind):
    masked = mask_secrets(f"use {secret} now")
    assert secret not in masked
    assert f"[REDACTED:{kind}]" in masked


def test_private_key_block_is_masked_whole():
    key = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\ndef\n-----END RSA PRIVATE KEY-----"
    masked = mask_secrets(f"before\n{key}\nafter")
    assert "MIIEabc" not in masked
    assert masked.startswith("before") and masked.endswith("after")


def test_truncated_private_key_is_masked_to_the_end():
    assert "MIIE" not in mask_secrets("-----BEGIN PRIVATE KEY-----\nMIIEsecret")


@pytest.mark.parametrize(
    "text",
    [
        'password = "hunter2hunter2"',
        "API_KEY: abcdef123456",
        "export GITHUB_TOKEN=abcdefgh12345678",
        "db.pwd='s3cr3tvalue'",
    ],
)
def test_assignments_keep_the_name_and_hide_the_value(text):
    masked = mask_secrets(text)
    assert "[REDACTED:secret]" in masked
    for value in ("hunter2hunter2", "abcdef123456", "abcdefgh12345678", "s3cr3tvalue"):
        assert value not in masked
    assert masked.split("=")[0].split(":")[0].strip()  # the name is still there


@pytest.mark.parametrize(
    "text",
    [
        "Plain sentence with no credential.",
        "The token budget is 4000.",  # no assignment of a long value
        "password = short",  # too short to be a credential
        "sk-short",
        "def f(secret): return secret",
    ],
)
def test_ordinary_text_is_left_alone(text):
    assert mask_secrets(text) == text


def test_masking_is_idempotent():
    once = mask_secrets("key=sk-abcdefghijklmnop1234 and password: hunter2hunter2")
    assert mask_secrets(once) == once


def test_email_is_masked():
    masked = mask_pii("write to jane.doe+work@example.co.uk please")
    assert "jane.doe" not in masked
    assert "[REDACTED:email]" in masked


@pytest.mark.parametrize("card", ["4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111"])
def test_valid_card_numbers_are_masked(card):
    assert mask_pii(f"card {card} expires soon") == "card [REDACTED:card_number] expires soon"


@pytest.mark.parametrize("number", ["4111111111111112", "1234567890123", "20260512093000"])
def test_long_numbers_that_are_not_cards_are_kept(number):
    # Order numbers, timestamps and ids are long too: the checksum tells them apart.
    assert mask_pii(f"id {number}") == f"id {number}"


def test_text_without_pii_is_unchanged():
    text = "Meeting at 10:30, room 4, contact the front desk."
    assert mask_pii(text) == text


def test_filter_output_masks_secrets_and_personal_data():
    out = filter_output(
        "mail jane@example.com, key sk-abcdefghijklmnop1234, card 4111 1111 1111 1111"
    )
    assert "jane@example.com" not in out
    assert "sk-abcdefghijklmnop1234" not in out
    assert "4111" not in out


def test_filter_output_keeps_ordinary_text():
    assert filter_output("Build finished in 3.2 s") == "Build finished in 3.2 s"


def test_check_input_allows_clean_arguments_unchanged():
    decision = check_input("run_code", {"code": "print(1)"})
    assert decision.allowed is True
    assert decision.replacement is None


def test_check_input_rewrites_arguments_that_hold_a_credential():
    decision = check_input("run_code", {"code": "key = 'sk-abcdefghijklmnop1234'\nprint(key)"})

    assert decision.allowed is True
    assert "sk-abcdefghijklmnop1234" not in decision.replacement["code"]
    assert "print(key)" in decision.replacement["code"]


def test_check_input_reaches_nested_values_but_not_keys():
    args = {"headers": {"sk-abcdefghijklmnop1234": ["Bearer abcdefghijklmnopqrstuvwxyz"]}, "n": 3}
    decision = check_input("web_search", args)

    assert decision.replacement["headers"]["sk-abcdefghijklmnop1234"] == ["[REDACTED:bearer_token]"]
    assert decision.replacement["n"] == 3


# --- Réponse du modèle filtrée pendant le streaming (EV2, ADR-0058) ---------------

def test_stream_redactor_masque_par_ligne_et_garde_le_reste():
    from sensai.execution.guardrails import StreamRedactor

    r = StreamRedactor()
    out = r.feed("Bearer abcdefghij") + r.feed("klmnopqrstuv ok\nmail : a@b.fr") + r.flush()
    assert "abcdefghijklmnop" not in out and "a@b.fr" not in out
    assert out.startswith("[REDACTED:bearer_token] ok\n")


def test_stream_redactor_cache_tout_le_corps_d_une_cle_privee():
    from sensai.execution.guardrails import StreamRedactor

    r = StreamRedactor()
    out = r.feed("avant\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nAAAA\n")
    out += r.feed("-----END RSA PRIVATE KEY-----\napres\n") + r.flush()
    assert "MIIEow" not in out and "AAAA" not in out
    assert out == "avant\n[REDACTED:private_key]\napres\n"
