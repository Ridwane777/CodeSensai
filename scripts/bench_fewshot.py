"""
Mesures de A7 (few-shot automatique) : où placer `fewshot_min_score` ?

Même méthode que `scripts/bench_cache.py` (A6) : pour chaque exemple de la
bibliothèque, on calcule la similarité (bge-m3, cosinus) avec :
- des **questions proches**, qui devraient recevoir cet exemple ;
- des **questions éloignées**, qui ne doivent **jamais** le recevoir — un
  mauvais exemple égare le modèle plus qu'un passage RAG hors sujet,
  ADR-0044.

Pas encore exécuté (pas d'Ollama avec bge-m3 disponible au moment d'écrire
ce script) : `DEFAULT_MIN_SCORE = 0.75` dans `knowledge/fewshot.py` reste
une **estimation**, pas une mesure. Faire tourner ce script sur le pod et
reporter les résultats dans docs/performance/A7-fewshot.md (revue PR #96).

    python scripts/bench_fewshot.py --host http://<pod>:11434 --out a7.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sensai.knowledge.rag import OllamaEmbedder  # noqa: E402

# (question de l'exemple, questions proches qui devraient le recevoir,
#  questions éloignées qui ne doivent jamais le recevoir)
CASES: list[tuple[str, list[str], list[str]]] = [
    ("Explique la fonction verifier_token",
     ["Comment marche verifier_token ?", "À quoi sert la fonction verifier_token ?"],
     ["Comment lancer les tests du projet ?", "Comment ajouter un utilisateur ?"]),
    ("Comment fonctionne le cache de réponses ?",
     ["Explique le cache sémantique", "Le cache A6, comment ça marche ?"],
     ["Comment configurer le RAG ?", "Comment changer de persona ?"]),
    ("Comment ajouter un utilisateur à la base ?",
     ["Comment créer un nouvel utilisateur ?", "Quelle est la marche pour ajouter un compte ?"],
     ["Comment supprimer un utilisateur ?", "Comment lire un fichier avec l'agent ?"]),
    ("Que fait l'outil search_codebase ?",
     ["Explique search_codebase", "À quoi sert l'outil de recherche dans le code ?"],
     ["Que fait l'outil write_file ?", "Comment fonctionne le planificateur X5 ?"]),
    ("Comment changer de persona en cours de session ?",
     ["Comment basculer de persona ?", "Comment utiliser /persona use ?"],
     ["Comment activer le mode debug ?", "Comment déployer en production ?"]),
]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def measure(embed, cases) -> tuple[list, list]:
    """(score, exemple, question) pour les questions proches et éloignées."""
    close, far = [], []
    for example_q, near, distant in cases:
        vectors = [np.array(v) for v in embed([example_q, *near, *distant])]
        for i, text in enumerate([*near, *distant]):
            row = (round(cosine(vectors[0], vectors[i + 1]), 4), example_q, text)
            (close if i < len(near) else far).append(row)
    return close, far


def report(close: list, far: list) -> None:
    print(f"\n== {len(close)} questions proches, {len(far)} questions éloignées ==")
    for threshold in (0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90):
        hits = sum(1 for row in close if row[0] >= threshold)
        wrong = [row for row in far if row[0] >= threshold]
        print(f"seuil {threshold:.2f} : {hits}/{len(close)} exemples utiles servis, "
              f"{len(wrong)}/{len(far)} exemples hors sujet servis "
              f"{[w[2] for w in wrong] if wrong else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seuil du few-shot automatique (A7)")
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", default="bge-m3")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    embed = OllamaEmbedder(args.host, args.model)
    close, far = measure(embed, CASES)
    report(close, far)
    if args.out:
        args.out.write_text(
            json.dumps({"close": close, "far": far}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
