"""
[Lot A — Fresnel] Budget de tokens et compression par résumé glissant —
feature [M2], ADR-0045.

Chaque tour, le nombre de tokens de ce qui serait envoyé au modèle est
estimé (approximation, pas un tokenizer réel — voir ADR-0045). Au-dessus
d'un budget, les tours les plus anciens sont remplacés par un seul résumé,
produit par un appel séparé au modèle de chat (même patron que `/structured`,
`core/structured.py` : un aller-retour, sans outils) et fondu dans le
prompt système — pas ajouté comme un second message `user`, qui casserait
l'alternance avec les tours gardés intacts (revue PR #97).

Rien de ceci ne touche `History.turns` ni la session sauvegardée (M1,
ADR-0007) : seuls les messages RÉELLEMENT ENVOYÉS à ce tour sont compactés.
Reprendre la session plus tard retrouve l'historique intact, en entier.
"""
from __future__ import annotations

from sensai.core.ollama_client import OllamaError, stream_chat_messages

CHARS_PER_TOKEN = 4  # approximation grossière (anglais/code) ; voir ADR-0045.
# Fenêtre de contexte envoyée à Ollama (options.num_ctx) : sans elle, Ollama
# tronque en silence à sa propre valeur par défaut (2048 ou 4096 selon la
# version), bien avant que le budget de tokens n'ait l'occasion d'agir. ESTIMATION
# (ADR-0045), pas une mesure : le modèle réellement utilisé peut en accepter plus.
DEFAULT_NUM_CTX = 8192
DEFAULT_KEEP_RECENT = 6  # tours (user+assistant) toujours gardés intacts
# Marge réservée à la réponse du modèle quand le budget est dérivé de
# num_ctx (ADR-0045) : sans elle, remplir tout num_ctx avec l'historique ne
# laisse plus de place pour répondre, et Ollama tronque quand même.
RESPONSE_MARGIN_TOKENS = 2000

SUMMARY_PROMPT = (
    "Résume la conversation suivante en un paragraphe compact, en gardant tous "
    "les faits, décisions et détails techniques importants (noms de fichiers, "
    "valeurs, erreurs rencontrées, décisions prises). N'invente rien, ne "
    "commente pas la consigne, renvoie uniquement le résumé."
)


class CompressionError(RuntimeError):
    """Le résumé n'a pas pu être produit (Ollama indisponible, réponse vide…)."""


def count_tokens(text: str) -> int:
    """Estimation grossière : ~4 caractères par token.

    Pas un tokenizer réel (ADR-0045, option écartée) : assez pour décider
    quand résumer, pas pour une mesure exacte de coût.
    """
    return max(1, len(text) // CHARS_PER_TOKEN)


def budget_from_num_ctx(num_ctx: int) -> int:
    """Budget de tokens dérivé de `num_ctx`, une marge de réponse retirée."""
    return max(1, num_ctx - RESPONSE_MARGIN_TOKENS)


def resolve_budget(max_tokens: int | None, num_ctx: int | None) -> int:
    """Le budget à appliquer : celui réglé explicitement, sinon dérivé de `num_ctx`.

    Un seul endroit décide du repli (revue PR #97 : deux valeurs par défaut
    différentes cohabitaient, 8000 ici et 6192 dans config.py).
    """
    if max_tokens is not None:
        return max_tokens
    return budget_from_num_ctx(num_ctx or DEFAULT_NUM_CTX)


def count_message_tokens(messages: list[dict]) -> int:
    """Estimation du total de tokens de `messages` (voir `count_tokens`)."""
    return sum(count_tokens(m.get("content", "")) for m in messages)


def exceeds_budget(messages: list[dict], max_tokens: int | None, num_ctx: int | None) -> bool:
    """Vrai si `messages` dépasse le budget. Combiné à `compressed == False` après
    `compress_messages`, ça veut dire « trop gros et impossible à réduire » : un
    dernier message gonflé par le RAG à lui seul, ou moins de tours que
    `keep_recent` (revue PR #97). L'appelant prévient alors l'utilisateur plutôt
    que de laisser Ollama tronquer sans rien dire."""
    return count_message_tokens(messages) > resolve_budget(max_tokens, num_ctx)


def summarize(host: str, model: str, turns: list[dict], num_ctx: int | None = None) -> str:
    """Un seul appel au modèle, sans outils, qui condense `turns` en texte.

    `turns` est borné à ce que `num_ctx` peut recevoir (moins la marge de
    réponse) avant l'envoi : sans ça, résumer des tours eux-mêmes trop
    nombreux pour la fenêtre du modèle se ferait tronquer en silence par
    Ollama, exactement le problème que M2 doit éviter (revue PR #97). Les
    tours les plus anciens de `turns` sont alors coupés en premier — ils
    sont déjà résumés plus loin dans le temps que les plus récents.

    CompressionError si Ollama est indisponible ou ne renvoie rien : jamais
    un résumé vide qui remplacerait silencieusement de vrais échanges.
    """
    transcript = "\n".join(f"{t['role']} : {t['content']}" for t in turns)
    if num_ctx:
        limit_chars = budget_from_num_ctx(num_ctx) * CHARS_PER_TOKEN
        if len(transcript) > limit_chars:
            transcript = "[…début tronqué, trop ancien pour entrer dans le contexte…]\n" + \
                transcript[-limit_chars:]
    messages = [
        {"role": "system", "content": SUMMARY_PROMPT},
        {"role": "user", "content": transcript},
    ]
    options = {"num_ctx": num_ctx} if num_ctx else None
    chunks: list[str] = []
    try:
        for message in stream_chat_messages(host, model, messages, options=options):
            if message.get("content"):
                chunks.append(message["content"])
    except OllamaError as e:
        raise CompressionError(str(e)) from e
    summary = "".join(chunks).strip()
    if not summary:
        raise CompressionError("le modèle n'a renvoyé aucun résumé")
    return summary


def compress_messages(
    host: str,
    model: str,
    messages: list[dict],
    max_tokens: int | None = None,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    num_ctx: int | None = None,
) -> tuple[list[dict], bool]:
    """Les messages à ENVOYER à ce tour ; `(messages, compressed)`.

    `messages` est celui que l'appelant envoie réellement au modèle —
    prompt système en tête, PUIS tout ce qui accompagne la question de ce
    tour (passages RAG, exemple few-shot, etc. : voir cli.py, qui compresse
    APRÈS les avoir ajoutés, pas avant, sinon le budget ne compterait pas
    ce qui part vraiment — revue PR #97). `max_tokens` vaut, s'il n'est pas
    donné, le budget dérivé de `num_ctx` (`resolve_budget`). Sous ce budget, ou s'il ne
    reste pas assez de tours anciens à résumer sans casser l'alternance
    user/assistant, `messages` revient inchangé. `CompressionError` se
    propage : l'appelant décide s'il continue quand même avec les tours
    bruts (voir cli.py).

    Le résumé est fondu dans le message système, jamais ajouté comme un
    second message `user` : deux `user` d'affilée, suivis d'un `assistant`,
    casseraient l'alternance que l'API attend.
    """
    max_tokens = resolve_budget(max_tokens, num_ctx)
    system = messages[:1] if messages and messages[0]["role"] == "system" else []
    turns = messages[len(system):]
    if count_message_tokens(messages) <= max_tokens or len(turns) <= keep_recent:
        return messages, False

    # Coupe sur une frontière paire : les tours sont ajoutés en paires
    # (add_user puis add_assistant), donc un index pair commence et finit
    # toujours sur la bonne alternance des deux côtés de la coupe.
    cut = len(turns) - keep_recent
    if cut % 2:
        cut -= 1
    if cut < 2:
        return messages, False

    to_summarize, recent = turns[:cut], turns[cut:]
    summary = summarize(host, model, to_summarize, num_ctx=num_ctx)
    note = (
        f"\n\n[Résumé automatique des {len(to_summarize)} échanges précédents, "
        f"généré pour respecter le budget de tokens (M2).]\n{summary}"
    )
    base = system[0]["content"] if system else ""
    new_system = [{"role": "system", "content": base + note}]
    return [*new_system, *recent], True
