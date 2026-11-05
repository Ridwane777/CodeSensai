"""
[Lot B — Méric] Confirmation utilisateur avant action risquée — feature [A3]
Human-in-the-Loop. S'applique avant tout appel à `run_code` (risque `execute`).

Contrat inter-lots (ADR-0005) : la façon de POSER la question vient de
l'interface. Ce module fournit celle de la CLI : un `Confirmer` à passer à
`ToolGateway(confirm=...)`. Celui du web (bouton « Autoriser ») est
`WebConfirmationBroker`, dans `web_confirmation.py` (ADR-0015) : à brancher par
le Lot D, sans toucher à la passerelle.

Règle : seul un « oui » explicite autorise. Réponse vide, inconnue, fin de
flux (stdin fermé, pipe, CI) ou interruption : refus.
"""
from __future__ import annotations

from collections.abc import Callable

from .gateway import ConfirmationRequest
from .tool_policy import Risk

_YES = frozenset({"o", "oui", "y", "yes"})


def format_request(request: ConfirmationRequest) -> str:
    """Le texte montré à l'utilisateur : l'outil, son risque et le plan exact."""
    return (
        f"\n⚠ L'agent veut utiliser « {request.tool} » (risque : {Risk(request.risk).value}).\n"
        f"{request.summary}\n"
        f"Délai de réponse : {request.timeout_s:g} s, sans réponse c'est un refus."
    )


def make_console_confirmer(
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> Callable[[ConfirmationRequest], bool]:
    """Fabrique le confirmeur de la CLI. `input_fn`/`output_fn` servent aux tests."""

    def confirm(request: ConfirmationRequest) -> bool:
        output_fn(format_request(request))
        try:
            answer = input_fn("Autoriser ? [o/N] ")
        except (EOFError, KeyboardInterrupt):
            output_fn("Pas de réponse : refusé.")
            return False
        allowed = answer.strip().lower() in _YES
        output_fn("Autorisé." if allowed else "Refusé.")
        return allowed

    return confirm


# Instance prête à l'emploi : `ToolGateway(registry, confirm=cli_confirm)`.
cli_confirm = make_console_confirmer()

