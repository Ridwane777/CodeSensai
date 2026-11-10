"""
A6 measurements (semantic cache): where should the similarity threshold go?

For each original question, we compute the similarity (bge-m3, cosine) with:
- **paraphrases**, which should be served from the cache;
- **traps**, close in wording but calling for a different answer, which must
  **never** be served (US-A6-2).

The dataset was written on 2026-10-18, before any measurement. Results and
choices: docs/performance/A6-cache.md.

The questions stay in French on purpose: they are the measured dataset (the
published numbers come from them) and they exercise the French roots of the
bilingual action rules in `sensai.knowledge.cache`. Translating them would
produce a different, unmeasured dataset.

    python scripts/bench_cache.py --host http://<ollama-host>:11434 --out a6.json
"""
# ruff: noqa: E501  (each question set fits on one line)
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sensai.knowledge.cache import conflict  # noqa: E402
from sensai.knowledge.rag import OllamaEmbedder  # noqa: E402

# (original question, paraphrases, traps)
CASES: list[tuple[str, list[str], list[str]]] = [
    ("Comment lancer les tests du projet ?",
     ["Quelle commande pour exécuter les tests ?", "Comment je fais tourner la suite de tests ?",
      "how do I run the tests?"],
     ["Comment écrire un nouveau test ?", "Comment ignorer un test qui échoue ?"]),
    ("Où est la configuration de la base de données ?",
     ["Dans quel fichier on configure la base de données ?", "Où se trouve la config de la BDD ?"],
     ["Comment migrer la base de données ?", "Où est la configuration du cache Redis ?"]),
    ("Comment ajouter un utilisateur ?",
     ["Comment créer un nouvel utilisateur ?", "Quelle est la marche pour ajouter un compte ?"],
     ["Comment supprimer un utilisateur ?", "Comment modifier un utilisateur ?"]),
    ("Comment lire un fichier avec l'agent ?",
     ["Quel outil permet à l'agent de lire un fichier ?"],
     ["Comment écrire un fichier avec l'agent ?", "Comment supprimer un fichier avec l'agent ?"]),
    ("Comment installer les dépendances Python ?",
     ["Quelle commande pour installer les dépendances ?", "Comment j'installe les paquets du projet ?"],
     ["Comment installer les dépendances JavaScript ?", "Comment mettre à jour les dépendances Python ?"]),
    ("Quel modèle utilise l'agent par défaut ?",
     ["C'est quoi le modèle par défaut de l'agent ?", "Quel LLM est utilisé par défaut ?"],
     ["Comment changer le modèle de l'agent ?", "Quel modèle d'embeddings utilise le RAG ?"]),
    ("Comment démarrer le serveur web ?",
     ["Comment lancer l'interface web ?", "Quelle commande démarre le serveur web ?"],
     ["Comment arrêter le serveur web ?", "Sur quel port tourne le serveur web ?"]),
    ("Pourquoi les tests échouent sur la CI ?",
     ["Pourquoi la CI est rouge ?"],
     ["Pourquoi les tests passent en local mais pas sur la CI ?", "Comment ajouter un job à la CI ?"]),
    ("Combien de temps sont gardées les sessions ?",
     ["Quelle est la durée de conservation des sessions ?",
      "Au bout de combien de jours les sessions sont supprimées ?"],
     ["Comment supprimer une session ?", "Combien de temps dure le préchargement du modèle ?"]),
    ("Quelle est la taille maximale d'un fichier indexé ?",
     ["Au-delà de quelle taille un fichier n'est plus indexé ?"],
     ["Quelle est la taille minimale d'un fichier indexé ?", "Quels types de fichiers sont indexés ?"]),
    ("Comment activer le mode debug ?",
     ["Comment passer en mode debug ?", "Comment avoir plus de logs ?"],
     ["Comment désactiver le mode debug ?"]),
    ("Que fait la fonction purge_sessions ?",
     ["À quoi sert purge_sessions ?", "Explique purge_sessions"],
     ["Que fait la fonction purge_facts ?", "Où est appelée purge_sessions ?"]),
    ("Comment déployer en production ?",
     ["Quelle est la procédure de mise en production ?"],
     ["Comment déployer en préproduction ?", "Comment revenir en arrière après un déploiement ?"]),
    ("Le projet supporte-t-il Windows ?",
     ["Est-ce que ça marche sous Windows ?"],
     ["Le projet supporte-t-il macOS ?"]),
    ("Comment corriger l'erreur ModuleNotFoundError ?",
     ["J'ai une ModuleNotFoundError, que faire ?"],
     ["Comment corriger l'erreur ImportError circular import ?", "Comment corriger l'erreur KeyError ?"]),
]


# Second dataset, written on 2026-10-18 after the first measurement but BEFORE
# writing the rules in `sensai.knowledge.cache`: it checks that they are not
# tailored to the first dataset.
HELD_OUT: list[tuple[str, list[str], list[str]]] = [
    ("Comment générer la documentation ?",
     ["Quelle commande pour construire la doc ?", "how to build the docs?"],
     ["Comment publier la documentation ?", "Comment générer le changelog ?"]),
    ("Où sont stockés les logs de l'application ?",
     ["Dans quel dossier sont écrits les logs ?", "Où trouver les fichiers de log ?"],
     ["Comment effacer les logs de l'application ?", "Où sont stockés les backups de l'application ?"]),
    ("Comment ouvrir une connexion à la base ?",
     ["Comment se connecter à la base de données ?"],
     ["Comment fermer une connexion à la base ?", "Comment ouvrir une connexion SSH ?"]),
    ("Quelle version de Python faut-il ?",
     ["Avec quelle version de Python le projet fonctionne ?", "Python 3 minimum requis ?"],
     ["Quelle version de Node faut-il ?", "Quelle version de Docker faut-il ?"]),
    ("Comment exporter les conversations en JSON ?",
     ["Comment sauvegarder une conversation au format JSON ?"],
     ["Comment importer les conversations en JSON ?", "Comment exporter les conversations en PDF ?"]),
    ("Que retourne la fonction load_settings ?",
     ["Quelle valeur renvoie load_settings ?"],
     ["Que retourne la fonction save_settings ?", "Quels paramètres prend load_settings ?"]),
    ("Comment augmenter le délai d'attente des requêtes ?",
     ["Comment allonger le timeout des requêtes HTTP ?"],
     ["Comment réduire le délai d'attente des requêtes ?", "Comment augmenter le nombre de requêtes en parallèle ?"]),
    ("Comment créer une branche Git ?",
     ["Quelle commande pour faire une nouvelle branche ?", "how do I create a git branch?"],
     ["Comment supprimer une branche Git ?", "Comment fusionner une branche Git ?"]),
    ("Le cache est-il activé par défaut ?",
     ["Par défaut, est-ce que le cache est actif ?"],
     ["Le cache est-il désactivé par défaut ?", "Le RAG est-il activé par défaut ?"]),
    ("Comment compter le nombre de sessions ?",
     ["Combien de sessions y a-t-il, comment le savoir ?"],
     ["Comment lister les sessions ?", "Comment compter le nombre de faits ?"]),
]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def measure(embed, cases) -> tuple[list, list]:
    """(score, question, other, conflict) for the paraphrases and for the traps."""
    paraphrases, traps = [], []
    for question, same, different in cases:
        vectors = [np.array(v) for v in embed([question, *same, *different])]
        for i, text in enumerate([*same, *different]):
            row = (round(cosine(vectors[0], vectors[i + 1]), 4), question, text,
                   conflict(question, text))
            (paraphrases if i < len(same) else traps).append(row)
    return paraphrases, traps


def report(name: str, paraphrases: list, traps: list) -> None:
    print(f"\n== {name}: {len(paraphrases)} paraphrases, {len(traps)} traps ==")
    for threshold in (0.70, 0.75, 0.80, 0.85, 0.90, 0.94):
        for label, rules in (("embeddings only", False), ("embeddings + rules", True)):
            def served(row, t=threshold, r=rules):
                return row[0] >= t and not (r and row[3])
            hits = sum(map(served, paraphrases))
            wrong = [row for row in traps if served(row)]
            print(f"threshold {threshold:.2f} {label:20}: {hits}/{len(paraphrases)} served, "
                  f"{len(wrong)}/{len(traps)} traps served {[w[2] for w in wrong] if rules else ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic cache threshold (A6)")
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", default="bge-m3")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    embed = OllamaEmbedder(args.host, args.model)
    results = {}
    for name, cases in (("set 1", CASES), ("held-out set", HELD_OUT)):
        paraphrases, traps = measure(embed, cases)
        report(name, paraphrases, traps)
        results[name] = {"paraphrases": paraphrases, "traps": traps}
    if args.out:
        args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
