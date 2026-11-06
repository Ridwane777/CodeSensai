"""
Paramètres de génération (ADR-0057) et débit réel (tokens/s) du modèle.

Quels paramètres de génération envoyer, et quel débit (tokens/s) sur nos
propres machines. Ce script joue le même jeu de questions, à réponse vérifiable,
sous plusieurs réglages, plusieurs fois chacun, et relève pour chaque réglage :

- justesse : la réponse contient ce qu'on attend (vérifié par une regex) ;
- stabilité : part des questions qui donnent la même réponse à chaque essai ;
- débit : tokens générés / seconde (eval_count / eval_duration, chiffres
  renvoyés par Ollama lui-même), et vitesse de lecture du prompt.

Le jeu a été écrit avant la mesure. Usage :

    python scripts/bench_generation.py --host http://<hôte-ollama>:11434 \
        --model qwen3-coder:30b --runs 3 --out docs/performance/data/generation.json

Sur le poste de développement (qwen3:8b, raisonnement coupé pour mesurer la réponse) :

    ollama pull qwen3:8b
    python scripts/bench_generation.py --host http://localhost:11434 --model qwen3:8b \
        --think off --runs 1 --out docs/performance/data/generation-laptop-qwen3-8b.json
"""
import argparse
import json
import re
import statistics
import time
from pathlib import Path

import requests

SYSTEM = "Tu es CodeSensei, un assistant de développement. Réponds brièvement."

# (question, regex que la bonne réponse doit contenir)
CASES = [
    ("En Python, que renvoie len([]) ? Réponds juste la valeur.", r"\b0\b"),
    ("Quelle commande lance les tests avec pytest en mode silencieux ? Juste la commande.",
     r"pytest\s+(-q|--quiet)"),  # --quiet ajouté après la mesure locale : même option
    ("Corrige ce code pour qu'une liste vide renvoie 0, réponds avec le code seul :\n"
     "def moyenne(notes):\n    return sum(notes) / len(notes)",
     # Corrigé après la première mesure : « if notes else 0 » est juste aussi.
     r"if\s+not\s+notes|len\(notes\)\s*==\s*0|if\s+notes\s+else\s+0"),
    ("Quel est le code HTTP d'une ressource introuvable ? Juste le nombre.", r"\b404\b"),
    ("Écris une fonction Python mediane(notes) qui renvoie la médiane d'une liste non vide. "
     # Corrigé après la première mesure : trier sur place (.sort()) donne aussi la médiane.
     "Code seul.", r"def\s+mediane\s*\(.*(sorted|\.sort\()"),
    ("Quel module de la bibliothèque standard Python sert à lire du JSON ? Un mot.",
     r"\bjson\b"),
]

# Jeu « hard » : le jeu basic est trop facile et sa grille a été élargie après coup.
# Écrit et committé AVANT toute mesure : sa grille ne change plus après les essais.
# Calcul, complexité, commandes, corrections de code et raisonnements à étapes.
HARD_CASES = [
    ("Que renvoie sorted([3, 1, 2], reverse=True) en Python ? La valeur seule.",
     r"\[\s*3\s*,\s*2\s*,\s*1\s*\]"),
    ('Que vaut "abc"[::-1] en Python ? La valeur seule.', r"cba"),
    ("Quelle est la complexité d'une recherche dichotomique dans une liste triée de n éléments ?",
     r"O\(\s*log\s*\(?\s*n\s*\)?\s*\)"),
    ("Quelle commande git crée une branche nommée fix et bascule dessus ? La commande seule.",
     r"git\s+(switch\s+-c|checkout\s+-b)\s+fix"),
    ("Quel code HTTP renvoie une API quand une ressource vient d'être créée ? Le nombre seul.",
     r"\b201\b"),
    ('Quelle exception lève int("x") en Python ? Le nom seul.', r"\bValueError\b"),
    ("Quelle option de pytest arrête la suite au premier échec ? L'option seule.",
     r"(?<![\w-])(-x|--exitfirst)\b"),
    ("Écris la requête SQL qui compte les lignes de la table users. La requête seule.",
     r"(?i)select\s+count\s*\(\s*\*\s*\)\s+from\s+users"),
    ("Quelle commande Docker liste les conteneurs en cours d'exécution ? La commande seule.",
     r"docker\s+(ps|container\s+ls)\b"),
    ("Quelle fonction du module json transforme un dict Python en chaîne JSON ? Le nom seul.",
     r"json\.dumps|\bdumps\b"),
    ("Quel verbe HTTP remplace entièrement une ressource existante ? Un mot.", r"\bPUT\b"),
    ("Que renvoie len(set([1, 1, 2])) en Python ? La valeur seule.", r"(?<![\d.])2(?![\d.])"),
    ("Quelle est la complexité moyenne d'une recherche par clé dans un dict Python ?",
     r"O\(\s*1\s*\)"),
    ("Corrige pour que la boucle aille de 1 à n inclus, code seul : for i in range(1, n): print(i)",
     r"range\(\s*1\s*,\s*n\s*\+\s*1\s*\)"),
    ("Écris en Python une fonction est_palindrome(s) qui renvoie True si s se lit pareil dans "
     "les deux sens. Code seul.", r"def\s+est_palindrome\s*\(.*(\[::-1\]|reversed)"),
    ("Que renvoie [x * x for x in range(1, 6)] en Python ? La valeur seule.",
     r"\[\s*1\s*,\s*4\s*,\s*9\s*,\s*16\s*,\s*25\s*\]"),
    ("Un fichier contient 3 fonctions de 10 lignes et 2 fonctions de 4 lignes. Combien de lignes "
     "de fonctions au total ? Le nombre seul.", r"(?<![\d.])38(?![\d.])"),
    ("Une requête prend 120 ms. On en lance 50 l'une après l'autre. Combien de secondes au total ? "
     "Le nombre seul.", r"(?<![\d.])6(?:[.,]0+)?(?![\d.])"),
    ("Un test échoue 1 fois sur 4. On le lance 2 fois de suite, indépendamment. Quelle est la "
     "probabilité qu'il réussisse les 2 fois ? En fraction.", r"9\s*/\s*16"),
    ("Une liste triée contient 1024 éléments. Combien de comparaisons au plus pour une recherche "
     "dichotomique ? Le nombre seul.", r"(?<![\d.])(10|11)(?![\d.])"),
    ("En Python 3.9+, avec quel opérateur fusionne-t-on deux dict a et b ? L'expression seule.",
     r"a\s*\|\s*b|\{\s*\*\*a\s*,\s*\*\*b\s*\}"),
    ("Corrige ce code pour qu'il ne plante pas sur une liste vide, code seul :\n"
     "def premier(l):\n    return l[0]", r"(if\s+not\s+l|len\(l\)\s*==\s*0|if\s+l\b|IndexError)"),
]

NUM_PREDICT = 512
REQUEST_TIMEOUT_S = 180

SETTINGS = {
    "ollama-defaults": {},
    "t0-seed": {"temperature": 0, "seed": 42},
    "t0.2-p0.9": {"temperature": 0.2, "top_p": 0.9},
    "t0.7-p0.9": {"temperature": 0.7, "top_p": 0.9},
    "t1.0": {"temperature": 1.0},
}


def ask(host, model, question, options, num_ctx, think=None):
    payload = {"model": model, "stream": False,
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": question}],
               # num_predict borné pour tous les réglages : sans limite, une génération
               # à haute température peut ne jamais s'arrêter (une requête bloquée 600 s
               # le 2026-11-02).
               "options": {**options, "num_ctx": num_ctx, "num_predict": NUM_PREDICT}}
    # qwen3 (dont qwen3:8b) raisonne par défaut avant de répondre : `think` le coupe
    # (off) ou le garde (on) ; non envoyé, le modèle fait comme il veut.
    if think is not None:
        payload["think"] = think
    started = time.monotonic()
    try:
        r = requests.post(f"{host.rstrip('/')}/api/chat", json=payload, timeout=REQUEST_TIMEOUT_S)
        r.raise_for_status()
        body = r.json()
    except requests.exceptions.Timeout:
        # Comptée comme une réponse fausse, pas comme un plantage de la mesure.
        body = {"message": {"content": ""}, "timed_out": True}
    message = body.get("message", {})
    return {
        # Le modèle tel qu'Ollama le nomme dans sa réponse, pas l'argument du script.
        "served_model": body.get("model", ""),
        "text": message.get("content", ""),
        "timed_out": bool(body.get("timed_out")),
        "thinking_chars": len(message.get("thinking") or ""),
        "wall_s": round(time.monotonic() - started, 2),
        "eval_count": body.get("eval_count", 0),
        "eval_s": body.get("eval_duration", 0) / 1e9,
        "prompt_count": body.get("prompt_eval_count", 0),
        "prompt_s": body.get("prompt_eval_duration", 0) / 1e9,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", required=True)
    parser.add_argument("--model", default="qwen3-coder:30b")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--set", choices=["basic", "hard"], default="basic", dest="case_set",
                        help="Jeu de questions : basic (6, la première mesure) ou hard (22)")
    parser.add_argument("--think", choices=["model", "on", "off"], default="model",
                        help="Raisonnement de qwen3 : off pour mesurer la réponse seule, "
                             "on pour le garder (compté dans eval_count), model : non envoyé")
    args = parser.parse_args()
    think = {"model": None, "on": True, "off": False}[args.think]
    cases = HARD_CASES if args.case_set == "hard" else CASES

    # Le modèle doit être installé : sinon Ollama répond 404 sans le dire clairement.
    tags = requests.get(f"{args.host.rstrip('/')}/api/tags", timeout=30).json()
    installed = {m.get("name") for m in tags.get("models", [])}
    if args.model not in installed and f"{args.model}:latest" not in installed:
        raise SystemExit(f"{args.model} n'est pas installé sur {args.host} : "
                         f"lancer `ollama pull {args.model}` (installés : {sorted(installed)})")

    # Chargement du modèle hors mesure : le premier appel paie le chargement.
    served = ask(args.host, args.model, "Bonjour.", {}, args.num_ctx, think)["served_model"]
    results = {}
    for name, options in SETTINGS.items():
        answers, rows = {}, []
        for _ in range(args.runs):
            for i, (question, pattern) in enumerate(cases):
                row = ask(args.host, args.model, question, options, args.num_ctx, think)
                row["case"], row["ok"] = i, bool(re.search(pattern, row["text"], re.S))
                answers.setdefault(i, []).append(row["text"].strip())
                rows.append(row)
        gen = [r["eval_count"] / r["eval_s"] for r in rows if r["eval_s"]]
        read = [r["prompt_count"] / r["prompt_s"] for r in rows if r["prompt_s"]]
        results[name] = {
            "options": options,
            "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3),
            "stable_cases": sum(len(set(v)) == 1 for v in answers.values()),
            "cases": len(cases),
            "gen_tokens_per_s_median": round(statistics.median(gen), 1) if gen else None,
            "prompt_tokens_per_s_median": round(statistics.median(read), 1) if read else None,
            "wall_s_median": round(statistics.median(r["wall_s"] for r in rows), 2),
            "rows": rows,
        }
        r = results[name]
        stable = f"{r['stable_cases']}/{r['cases']}"
        print(f"{name:16} justesse {r['accuracy']:.0%}  stables {stable}  "
              f"génération {r['gen_tokens_per_s_median']} tok/s  lecture "
              f"{r['prompt_tokens_per_s_median']} tok/s  {r['wall_s_median']} s/réponse",
              flush=True)
        save(args, served, results)
    save(args, served, results)


def save(args, served, results) -> None:
    """Écrit les résultats déjà obtenus : appelé après chaque réglage."""
    if args.out:
        report = {"model": served, "requested_model": args.model, "think": args.think,
                  "case_set": args.case_set, "runs": args.runs, "num_ctx": args.num_ctx,
                  "num_predict": NUM_PREDICT, "date": time.strftime("%Y-%m-%d"),
                  "results": results}
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
