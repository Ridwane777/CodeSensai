"""
[Lot A — Fresnel] Personas de l'agent — feature [A5], ADR-0042 et ADR-0043.

Le nom, le ton, le rôle et le périmètre de l'agent sont lus depuis
`config.json` (section `personas`), jamais codés en dur : le même système
devient un assistant juridique ou un tuteur de maths sans toucher au code.

La persona active n'est qu'une étiquette gardée en mémoire par la boucle du
CLI (`cli.py`) : changer de persona ne touche jamais `History.turns`, donc
le contexte de la conversation survit au changement, comme l'exige le
catalogue.

ADR-0043 ajoutait trois enrichissements ; seul reste la restriction d'outils par
persona (`tools.disabled`). Le routage par mots-clés et l'ajout d'une persona à la
volée (`/persona add`) ont été retirés (ADR-0056, point 4) : ils servaient une
plateforme multi-usage, pas le scénario de Camille.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_PERSONA_ID = "assistant"
DEFAULT_PERSONA = {
    "id": DEFAULT_PERSONA_ID,
    "name": "Sensai",
    "role": "assistant de développement",
    "tone": "neutre et précis",
    "scope": "le projet courant",
}


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    role: str
    tone: str
    scope: str
    # Routage automatique (ADR-0043) : si un de ces mots apparaît dans la
    # question, et que cette persona n'est pas déjà active, on y bascule.
    # Restriction d'outils (ADR-0043) : noms d'outils retirés de ceux déjà
    # désactivés par la config globale, tant que cette persona est active.
    tools_disabled: frozenset[str] = field(default_factory=frozenset)

    def as_prompt(self) -> str:
        return (
            f"Pour cette session, tu es {self.name}. Ton rôle : {self.role}. "
            f"Ton ton : {self.tone}. Périmètre de réponse : {self.scope} — "
            "si une question en sort, dis-le plutôt que d'y répondre quand même."
        )


class PersonaError(ValueError):
    """Persona inconnue ou configuration invalide : le message dit quoi faire."""


class PersonaStore:
    """Les profils disponibles, lus une fois au démarrage depuis `config.json`,
    et complétables en session par `/persona add` (ADR-0043).

    Toujours au moins une persona (`DEFAULT_PERSONA`) : un projet sans section
    `personas` dans sa config continue de fonctionner sans rien configurer.
    """

    def __init__(self, profiles: list[Persona], default_id: str):
        if not profiles:
            raise PersonaError("personas : au moins un profil est requis")
        self._profiles = {p.id: p for p in profiles}
        if default_id not in self._profiles:
            known = ", ".join(sorted(self._profiles)) or "aucune"
            raise PersonaError(f"personas : persona par défaut inconnue : {default_id} "
                                f"(connues : {known})")
        self.default_id = default_id

    @classmethod
    def from_config(cls, data: dict | None) -> PersonaStore:
        """`data` : la valeur de `config.json["personas"]`, ou None/absente.

        Toute entrée qui n'a pas la forme attendue — `data` autre chose qu'un
        dict, un profil qui n'est pas un dict, un champ absent, vide ou pas
        une chaîne — lève PersonaError plutôt qu'une AttributeError/TypeError
        Python : une config mal écrite doit s'arrêter avec un message clair,
        jamais une trace de la CLI.
        """
        if data is None:
            return cls([Persona(**DEFAULT_PERSONA)], DEFAULT_PERSONA_ID)
        if not isinstance(data, dict):
            raise PersonaError("personas : un objet est attendu (id/name/role/tone/scope)")
        profiles_raw = data.get("profiles")
        if not isinstance(profiles_raw, list) or not profiles_raw:
            raise PersonaError("personas.profiles : liste non vide attendue")
        profiles = []
        seen_ids: set[str] = set()
        for i, raw in enumerate(profiles_raw):
            if not isinstance(raw, dict):
                raise PersonaError(f"personas.profiles[{i}] : un objet est attendu")
            missing = {"id", "name", "role", "tone", "scope"} - raw.keys()
            if missing:
                raise PersonaError(f"personas.profiles[{i}] : champ(s) manquant(s) : "
                                    f"{', '.join(sorted(missing))}")
            for field_name in ("id", "name", "role", "tone", "scope"):
                value = raw[field_name]
                if not isinstance(value, str) or not value.strip():
                    raise PersonaError(
                        f"personas.profiles[{i}].{field_name} : chaîne non vide attendue"
                    )
            if raw["id"] in seen_ids:
                raise PersonaError(f"personas.profiles : id en double : {raw['id']}")
            seen_ids.add(raw["id"])
            if "keywords" in raw:
                # Routage par mots-clés retiré (ADR-0056, point 4) : une clé qui ne fait
                # plus rien ne doit pas passer pour active.
                raise PersonaError(f"personas.profiles[{i}].keywords : le routage par "
                                   "mots-clés a été retiré (ADR-0056) ; changer de persona "
                                   "avec /persona use ou le sélecteur du web")
            tools_cfg = raw.get("tools") or {}
            disabled = tools_cfg.get("disabled", [])
            if not isinstance(disabled, list) or not all(isinstance(n, str) for n in disabled):
                raise PersonaError(
                    f"personas.profiles[{i}].tools.disabled : liste de noms d'outils attendue"
                )
            profiles.append(Persona(
                id=raw["id"], name=raw["name"], role=raw["role"],
                tone=raw["tone"], scope=raw["scope"],
                tools_disabled=frozenset(disabled),
            ))
        default_id = data.get("default", profiles[0].id)
        if not isinstance(default_id, str):
            raise PersonaError("personas.default : une chaîne est attendue")
        return cls(profiles, default_id)

    def names(self) -> list[str]:
        return sorted(self._profiles)

    def get(self, persona_id: str) -> Persona:
        try:
            return self._profiles[persona_id]
        except KeyError:
            known = ", ".join(self.names())
            raise PersonaError(f"persona inconnue : {persona_id} (connues : {known})") from None

    def default(self) -> Persona:
        return self._profiles[self.default_id]


def handle_persona_command(
    line: str, store: PersonaStore, active_id: str
) -> tuple[str, str] | None:
    """`/persona`, `/persona list`, `/persona use <id>`.

    Retourne `(texte affiché, id actif après la commande)`, ou None si `line`
    n'est pas une commande `/persona` (elle part alors au modèle comme
    d'habitude).
    """
    words = line.split(maxsplit=2)
    if not words or words[0] != "/persona":
        return None
    if len(words) == 1:
        active = store.get(active_id)
        return f"Persona active : {active.id} ({active.name}, {active.role}).", active_id
    if words[1] == "list":
        lines = []
        for name in store.names():
            p = store.get(name)
            marque = "*" if name == active_id else " "
            lines.append(f"{marque} {p.id} — {p.name}, {p.role}")
        return "\n".join(lines), active_id
    if words[1] == "use" and len(words) == 3:
        try:
            new_persona = store.get(words[2].strip())
        except PersonaError as e:
            return f"[Erreur] {e}", active_id
        return (f"Persona changée : {new_persona.id} ({new_persona.name}). "
                "L'historique de la conversation est conservé."), new_persona.id
    return (
        "Usage : /persona | /persona list | /persona use <id>"
    ), active_id
