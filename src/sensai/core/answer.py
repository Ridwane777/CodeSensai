"""
Le texte de la réponse d'un tour, tel qu'il est enregistré (session M1, cache A6).

Le modèle écrit parfois un peu de texte, appelle un outil, puis écrit la suite —
voire réécrit la même réponse. Concaténés tels quels, ces morceaux donnaient
« …le fichier.Le fichier… » dans la session enregistrée (essai réel du
2026-11-01). Ici, chaque morceau séparé par un appel d'outil devient un
paragraphe, et un morceau que le modèle réécrit ensuite est retiré, à l'identique
ou reformulé (essai du 2026-11-01 après-midi : « …is located in `stats.py`… »
puis « …is defined in `stats.py`… »).
"""
from __future__ import annotations

import re

_STRAY_TAGS = re.compile(r"</?tool_call>")

# En dessous, deux morceaux qui commencent pareil peuvent être une coïncidence
# (« D'accord. »), pas une réponse réécrite.
MIN_REPEAT_CHARS = 30
# Part des mots d'un morceau retrouvés dans un morceau suivant à partir de laquelle
# c'est une reformulation. Une annonce (« Je lis stats.py. ») reste bien en dessous.
REPHRASE_OVERLAP = 0.8

_WORD = re.compile(r"\w[\w'-]*")


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


def _rephrased_later(part: str, later: list[str]) -> bool:
    """Vrai si presque tous les mots de `part` reviennent dans un morceau suivant."""
    words = _words(part)
    if len(part) < MIN_REPEAT_CHARS or not words:
        return False
    return any(len(words & _words(p)) / len(words) >= REPHRASE_OVERLAP for p in later)


class AnswerBuilder:
    def __init__(self) -> None:
        self._segments: list[str] = [""]

    def add(self, text: str) -> None:
        """Un morceau de texte (événement Token)."""
        self._segments[-1] += text

    def tool_boundary(self) -> None:
        """Un appel d'outil : le texte qui suit est un nouveau morceau."""
        if self._segments[-1]:
            self._segments.append("")

    def text(self) -> str:
        # Une balise <tool_call> vide laissée par le modèle n'a rien à faire dans la réponse.
        parts = [p for p in (_STRAY_TAGS.sub("", s).strip() for s in self._segments) if p]
        kept = []
        for i, part in enumerate(parts):
            later = parts[i + 1:]
            repeated = ((len(part) >= MIN_REPEAT_CHARS and any(p.startswith(part) for p in later))
                        or _rephrased_later(part, later))
            if not repeated and part not in kept:
                kept.append(part)
        return "\n\n".join(kept)
