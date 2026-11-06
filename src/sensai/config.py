"""
Chargement de la configuration : modèle, host Ollama, chemin du prompt système.

Priorité : argument CLI > config.json > valeurs par défaut.
Rien de tout ça n'est codé en dur dans la logique de l'application.
"""
import argparse
import json
from pathlib import Path

from sensai.core.agent import MAX_ITERATIONS
from sensai.core.ollama_client import DEFAULT_REQUEST_TIMEOUT, GENERATION_KEYS
from sensai.execution.file_permissions import FilePermissions
from sensai.execution.tool_policy import ToolPreferences
from sensai.knowledge.compression import DEFAULT_NUM_CTX, budget_from_num_ctx
from sensai.knowledge.persona import PersonaError, PersonaStore
from sensai.knowledge.prompt_versions import INDEX_FILE, PromptStore
from sensai.tools.mcp_tool import parse_mcp_config

# Racine du dépôt : config.py est dans src/sensai/, donc deux niveaux au-dessus.
# Sans ça, `config.json` et `prompts/` n'étaient trouvés que si on lançait la
# commande depuis le dossier du projet — or `sensai` est une commande installée,
# et un assistant de code se lance justement depuis le projet de l'utilisateur.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG_PATH = "config.json"
# Modèle de dev retenu par docs/recherche/model-choices.md : assez petit pour itérer vite,
# et il supporte le tool calling natif d'Ollama (exigence d'ADR-0003).
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_HOST = "http://localhost:11434"
DEFAULT_SYSTEM_PROMPT_PATH = "prompts/system_prompt.txt"
# Consigne ajoutée quand une session est reprise (feature M1, ADR-0007).
DEFAULT_MEMORY_PROMPT_PATH = "prompts/memory_prompt.txt"
# Durée de conservation des sessions (ADR-0007) : 30 jours, comme Claude Code.
DEFAULT_RETENTION_DAYS = 30
# RAG (ADR-0009) : modèle et seuil choisis par mesure, docs/performance/R1-rag.md.
DEFAULT_RAG_MODEL = "bge-m3"
DEFAULT_RAG_MIN_SCORE = 0.54
DEFAULT_RAG_TOP_K = 5
# Few-shot automatique (A7, ADR-0044) : plus strict que le RAG, mais seuil ESTIMÉ,
# pas mesuré — voir fewshot.py et scripts/bench_fewshot.py.
DEFAULT_FEWSHOT_MIN_SCORE = 0.75
# Budget de tokens (M2, ADR-0045) : DEFAULT_NUM_CTX (importé de compression.py)
# est la fenêtre envoyée à Ollama ; le budget en est dérivé (une marge de
# réponse retirée) plus bas, après lecture de la ligne de commande.
DEFAULT_TOKEN_BUDGET_KEEP_RECENT = 6
# Paramètres de génération envoyés à Ollama (ADR-0057). Température basse : un
# assistant de code doit donner la même commande, le même chemin, le même appel
# d'outil d'une fois sur l'autre. Valeurs comparées avec le vrai modèle :
# docs/performance/generation-parameters.md (scripts/bench_generation.py).
DEFAULT_GENERATION = {"temperature": 0.2, "top_p": 0.9}


def resolve_path(path: str) -> Path | None:
    """
    Cherche `path` d'abord dans le dossier courant (pour qu'un utilisateur puisse
    poser son propre config.json à côté de son projet), puis dans la racine du
    dépôt. Retourne None si le fichier n'existe nulle part.
    """
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None

    for root in (Path.cwd(), PROJECT_ROOT):
        resolved = root / candidate
        if resolved.is_file():
            return resolved
    return None


def load_config_file(path: str = DEFAULT_CONFIG_PATH) -> dict:
    resolved = resolve_path(path)
    if resolved is None:
        return {}
    with open(resolved, encoding="utf-8") as f:
        return json.load(f)


def generation_from_config(file_config: dict) -> dict:
    """Les paramètres de génération de config.json, défauts compris (ADR-0057), pour
    les commandes qui ne passent pas par `get_settings()`. ValueError si une clé est
    inconnue : un paramètre mal orthographié ne doit pas passer pour actif."""
    section = file_config.get("generation") or {}
    unknown = set(section) - set(GENERATION_KEYS)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"config.json : paramètre de génération inconnu : {names}")
    return {k: v for k, v in {**DEFAULT_GENERATION, **section}.items() if v is not None}


def max_iterations_from_config(file_config: dict) -> int:
    """Le `max_iterations` de config.json (ou le défaut), même usage que ci-dessus."""
    value = file_config.get("max_iterations", MAX_ITERATIONS)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 50:
        raise ValueError(
            f"config.json : max_iterations doit être un entier de 1 à 50 (reçu : {value!r})")
    return value


def request_timeout_from_config(file_config: dict) -> int:
    """Le `request_timeout` de config.json (ou le défaut), en secondes : combien
    attendre Ollama avant d'abandonner. Sur CPU, plusieurs minutes sont normales."""
    value = file_config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(
            f"config.json : request_timeout doit être un entier positif (reçu : {value!r})")
    return value


def num_ctx_from_config(file_config: dict) -> int:
    """Le `num_ctx` de config.json (ou le défaut), pour les commandes qui ne passent
    pas par `get_settings()` (`sensai-schedule`, `sensai-eval`).

    Lève ValueError si la valeur n'est pas un entier positif : mieux vaut s'arrêter
    que d'envoyer à Ollama une fenêtre absurde qu'il ignorerait en silence.
    """
    value = file_config.get("num_ctx", DEFAULT_NUM_CTX)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"config.json : num_ctx doit être un entier positif (reçu : {value!r})")
    return value


def load_system_prompt(path: str) -> str:
    """Charge le prompt système depuis un fichier (jamais codé en dur)."""
    resolved = resolve_path(path)
    if resolved is None:
        return ""
    return resolved.read_text(encoding="utf-8").strip()


def prompts_dir() -> Path:
    """Dossier du registre de prompts (A4, ADR-0010) : celui du dossier courant
    s'il en a un, sinon celui du dépôt — même règle que `resolve_path`."""
    index = resolve_path(f"prompts/{INDEX_FILE}")
    return index.parent if index else PROJECT_ROOT / "prompts"


def load_prompts(system_path: str | None, memory_path: str | None) -> tuple[str, str, dict]:
    """Prompts système et mémoire, et les versions utilisées (A4, ADR-0010).

    L'agent lit la version qui porte le marque-page du registre. Un fichier
    donné explicitement (`--system-prompt`, `config.json`) garde la priorité :
    c'est ainsi qu'on essaie un brouillon avant de le ranger. Sans registre
    (branches qui n'ont pas encore A4), on relit les anciens fichiers.
    """
    store = PromptStore(prompts_dir())
    texts, versions = {}, {}
    defaults = {"system": DEFAULT_SYSTEM_PROMPT_PATH, "memory": DEFAULT_MEMORY_PROMPT_PATH}
    for name, explicit in (("system", system_path), ("memory", memory_path)):
        if explicit:
            texts[name] = load_system_prompt(explicit)
            versions[name] = f"{Path(explicit).name} (non rangé)"
        elif store.exists() and name in store.names():
            texts[name] = store.load(name).strip()
            versions[name] = store.active(name)
        else:
            texts[name] = load_system_prompt(defaults[name])
    return texts["system"], texts["memory"], versions


def get_settings(argv: list[str] | None = None, prog: str | None = None) -> dict:
    """Réglages du CLI : config.json, puis la ligne de commande.

    `argv` : les arguments à lire à la place de sys.argv. `sensai-web` (ADR-0035)
    lit d'abord ses propres options, puis passe le reste ici pour accepter les
    mêmes réglages que le CLI.
    """
    file_config = load_config_file()

    parser = argparse.ArgumentParser(prog=prog, description="Sensai — CodeSensei CLI")
    parser.add_argument(
        "--model",
        default=file_config.get("model", DEFAULT_MODEL),
        help="Nom du modèle Ollama à utiliser",
    )
    parser.add_argument(
        "--host",
        default=file_config.get("host", DEFAULT_HOST),
        help="URL de l'API Ollama",
    )
    parser.add_argument(
        "--system-prompt",
        dest="system_prompt_path",
        # Sans valeur explicite, la version active du registre (A4, ADR-0010).
        default=file_config.get("system_prompt_path"),
        help="Fichier de prompt système à utiliser à la place de la version active",
    )
    # Persistance des sessions (feature M1, ADR-0007).
    parser.add_argument(
        "--session",
        default=None,
        help="Identifiant d'une session à reprendre (défaut : la dernière du projet)",
    )
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Démarrer une nouvelle session au lieu de reprendre la dernière",
    )
    parser.add_argument(
        "--data-dir",
        default=file_config.get("data_dir"),
        help="Dossier des sessions et du profil (défaut : $SENSAI_HOME, sinon ~/.sensai)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=file_config.get("retention_days", DEFAULT_RETENTION_DAYS),
        help="Supprimer au démarrage les sessions sans message depuis N jours (0 : jamais)",
    )
    # RAG sur le projet (feature R1, ADR-0009).
    parser.add_argument(
        "--no-rag",
        dest="rag",
        action="store_false",
        default=file_config.get("rag", True),
        help="Ne pas chercher dans les fichiers du projet",
    )
    parser.add_argument(
        "--rag-model",
        default=file_config.get("rag_model", DEFAULT_RAG_MODEL),
        help="Modèle Ollama d'embeddings pour la recherche dans le projet",
    )
    parser.add_argument(
        "--rag-min-score",
        type=float,
        default=file_config.get("rag_min_score", DEFAULT_RAG_MIN_SCORE),
        help="Similarité minimale d'un passage pour être envoyé au modèle (0 à 1)",
    )
    parser.add_argument(
        "--rag-top-k",
        type=int,
        default=file_config.get("rag_top_k", DEFAULT_RAG_TOP_K),
        help="Nombre maximal de passages envoyés au modèle par question",
    )
    # Reclassement par le modèle de chat (R2, ADR-0032) : environ 3 s de plus.
    parser.add_argument(
        "--no-rag-rerank",
        dest="rag_rerank",
        action="store_false",
        default=file_config.get("rag_rerank", True),
        help="Ne pas faire reclasser les passages trouvés par le modèle (plus rapide)",
    )
    # Cache des réponses (A6, ADR-0033) : désactivé par défaut depuis l'ADR-0056 (peu de
    # questions se répètent pour un développeur seul) ; `--cache` ou "cache": true l'active.
    parser.add_argument(
        "--cache",
        dest="cache",
        action="store_true",
        default=file_config.get("cache", False),
        help="Servir et enregistrer les réponses en cache (A6)",
    )
    parser.add_argument(
        "--no-cache",
        dest="cache",
        action="store_false",
        help="Ne pas servir ni enregistrer de réponses en cache (défaut)",
    )
    # Few-shot automatique (A7, ADR-0044) : désactivé sans fichier d'exemples.
    parser.add_argument(
        "--fewshot-examples",
        dest="fewshot_examples",
        default=file_config.get("fewshot_examples"),
        help="Fichier JSONL d'exemples (format sensai-eval) pour le few-shot automatique",
    )
    parser.add_argument(
        "--fewshot-min-score",
        type=float,
        default=file_config.get("fewshot_min_score", DEFAULT_FEWSHOT_MIN_SCORE),
        help="Similarité minimale pour qu'un exemple soit ajouté à la question (0 à 1)",
    )
    # Fenêtre de contexte (M2, ADR-0045) : voir options.num_ctx de l'API Ollama.
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=file_config.get("num_ctx", DEFAULT_NUM_CTX),
        help="Fenêtre de contexte envoyée à Ollama (options.num_ctx)",
    )
    # Paramètres de génération (ADR-0057) : section `generation` de config.json,
    # chaque clé remplaçable en ligne de commande. Défauts : DEFAULT_GENERATION.
    generation = {**DEFAULT_GENERATION, **(file_config.get("generation") or {})}
    parser.add_argument("--temperature", type=float, default=generation.get("temperature"),
                        help="Température de génération (0 : la plus prévisible)")
    parser.add_argument("--top-p", type=float, default=generation.get("top_p"),
                        help="Échantillonnage nucleus (0 à 1)")
    parser.add_argument("--seed", type=int, default=generation.get("seed"),
                        help="Graine : mêmes réponses à paramètres égaux (essais reproductibles)")
    parser.add_argument("--num-predict", type=int, default=generation.get("num_predict"),
                        help="Nombre maximal de tokens générés par réponse (-1 : sans limite)")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=file_config.get("max_iterations", MAX_ITERATIONS),
        help="Nombre maximal d'appels au modèle par tour (garde-fou anti-boucle)",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=file_config.get("request_timeout", DEFAULT_REQUEST_TIMEOUT),
        help="Secondes d'attente d'une réponse d'Ollama (sur CPU, plusieurs minutes)",
    )
    # Budget de tokens et résumé glissant (M2, ADR-0045) : activé par défaut,
    # le catalogue demande un déclenchement automatique en approchant la limite.
    parser.add_argument(
        "--no-token-budget",
        dest="token_budget",
        action="store_false",
        default=file_config.get("token_budget", True),
        help="Envoyer l'historique complet au modèle, sans résumer les tours anciens",
    )
    parser.add_argument(
        "--token-budget-max",
        type=int,
        # Pas de défaut ici : argparse évalue un défaut AVANT de lire argv, donc
        # un défaut dérivé de num_ctx ignorerait un `--num-ctx` passé en ligne de
        # commande (revue PR #97). On le dérive plus bas, une fois num_ctx connu.
        default=file_config.get("token_budget_max"),
        help="Tokens (estimés) au-delà desquels les tours anciens sont résumés "
             "(défaut : num_ctx moins une marge pour la réponse)",
    )
    parser.add_argument(
        "--token-budget-keep-recent",
        type=int,
        default=file_config.get("token_budget_keep_recent", DEFAULT_TOKEN_BUDGET_KEEP_RECENT),
        help="Nombre de tours récents toujours gardés intacts, jamais résumés",
    )
    args = parser.parse_args(argv)
    if args.retention_days < 0:
        # Une durée négative purgerait toutes les sessions : on refuse au lieu de deviner.
        parser.error("--retention-days doit être positif ou nul (0 : ne jamais purger)")
    if not 0 <= args.rag_min_score <= 1:
        parser.error("--rag-min-score doit être compris entre 0 et 1")
    if args.rag_top_k < 1:
        parser.error("--rag-top-k doit être au moins 1")
    if not 0 <= args.fewshot_min_score <= 1:
        parser.error("--fewshot-min-score doit être compris entre 0 et 1")
    if args.num_ctx < 1:
        parser.error("--num-ctx doit être au moins 1")
    unknown = set(file_config.get("generation") or {}) - set(GENERATION_KEYS)
    if unknown:
        # Comme tools/files : un paramètre mal orthographié ne doit pas passer pour actif.
        names = ", ".join(sorted(unknown))
        parser.error(f"config.json : paramètre de génération inconnu : {names} "
                     f"(acceptés : {', '.join(GENERATION_KEYS)})")
    if args.temperature is not None and not 0 <= args.temperature <= 2:
        parser.error("--temperature doit être comprise entre 0 et 2")
    if args.top_p is not None and not 0 < args.top_p <= 1:
        parser.error("--top-p doit être compris entre 0 (exclu) et 1")
    if args.num_predict is not None and args.num_predict == 0:
        parser.error("--num-predict doit être positif, ou -1 pour ne pas limiter")
    if not 1 <= args.max_iterations <= 50:
        parser.error("--max-iterations doit être compris entre 1 et 50")
    if args.request_timeout < 1:
        parser.error("--request-timeout doit être au moins 1")
    if args.token_budget_max is None:
        args.token_budget_max = budget_from_num_ctx(args.num_ctx)
    if args.token_budget_max < 1:
        parser.error("--token-budget-max doit être au moins 1")
    if args.token_budget_max >= args.num_ctx:
        # Un budget au moins aussi grand que la fenêtre ne protège de rien : Ollama
        # tronquerait avant que le résumé ne se déclenche.
        parser.error(
            f"--token-budget-max ({args.token_budget_max}) doit rester sous --num-ctx "
            f"({args.num_ctx}), avec de la place pour la réponse"
        )
    if args.token_budget_keep_recent < 2:
        # Moins de 2 : rien à garder en entier ne survit à la coupe (cf.
        # compress_messages, qui exige une paire au moins de chaque côté).
        parser.error("--token-budget-keep-recent doit être au moins 2")
    # Sections `tools` (préférences de la passerelle, docs/architecture/tool-contract.md) et
    # `files` (dossiers autorisés, ADR-0011). Une clé inconnue arrête le CLI :
    # une restriction mal orthographiée ne doit pas passer pour active.
    try:
        tool_preferences = ToolPreferences.from_dict(file_config.get("tools") or {})
        file_permissions = FilePermissions.from_dict(file_config.get("files"))
        # Serveurs MCP (T1, ADR-0041) : vérifiés ici, lancés par le CLI ou le web.
        mcp_servers = parse_mcp_config(file_config.get("mcp_servers"))
    except (ValueError, TypeError) as e:
        parser.error(f"config.json : {e}")
    # Personas (A5, ADR-0042) : une persona par défaut inconnue ou un profil
    # incomplet arrête le CLI, comme pour tools/files ci-dessus.
    try:
        personas = PersonaStore.from_config(file_config.get("personas"))
    except PersonaError as e:
        parser.error(f"config.json : {e}")

    system_prompt, memory_prompt, prompt_versions = load_prompts(
        args.system_prompt_path, file_config.get("memory_prompt_path")
    )
    return {
        "model": args.model,
        "host": args.host,
        "system_prompt": system_prompt,
        "memory_prompt": memory_prompt,
        "prompt_versions": prompt_versions,
        "session": args.session,
        "new_session": args.new_session,
        "data_dir": args.data_dir,
        "retention_days": args.retention_days,
        "rag": args.rag,
        "rag_model": args.rag_model,
        "rag_min_score": args.rag_min_score,
        "rag_top_k": args.rag_top_k,
        "rag_rerank": args.rag_rerank,
        "cache": args.cache,
        "fewshot_examples": args.fewshot_examples,
        "fewshot_min_score": args.fewshot_min_score,
        "num_ctx": args.num_ctx,
        "generation": {k: v for k, v in {
            **generation, "temperature": args.temperature, "top_p": args.top_p,
            "seed": args.seed, "num_predict": args.num_predict,
        }.items() if v is not None},
        "max_iterations": args.max_iterations,
        "request_timeout": args.request_timeout,
        "token_budget": args.token_budget,
        "token_budget_max": args.token_budget_max,
        "token_budget_keep_recent": args.token_budget_keep_recent,
        "tool_preferences": tool_preferences,
        "file_permissions": file_permissions,
        "mcp_servers": mcp_servers,
        # Règles de refus ajoutées par l'utilisateur (EV2, ADR-0027) : validées
        # au démarrage par InputRules.from_config, pas ici.
        "input_blocklist": file_config.get("input_blocklist"),
        # Liens de partage publics (X3) : désactivés par défaut (ADR-0056).
        "share_links": file_config.get("share_links", False) is True,
        # Personas (A5, ADR-0042).
        "personas": personas,
    }
