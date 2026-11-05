"""
[Lot C — Ridwane] Registre des versions de prompts — feature [A4] Prompt
Versioning, ADR-0010.

Principe repris des outils du métier (Langfuse, PromptLayer…) : une version est
immuable, le marque-page `active` est mobile. L'agent lit la version marquée ;
revenir en arrière consiste à déplacer le marque-page, sans rien recopier ni
effacer.

Sur disque, dans le dossier `prompts/` du dépôt :

    versions.json        l'index : pour chaque prompt, `active` + ses versions
    system/v1.txt        une version = un fichier, jamais modifié
    memory/v1.txt

Chaque version garde son empreinte sha256 : ce n'est pas un identifiant (on
désigne une version par son numéro), c'est ce qui permet à `check()` — et donc
à la CI — de repérer une version modifiée après coup.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from datetime import date as Date
from pathlib import Path

INDEX_FILE = "versions.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    # Les prompts sont chargés avec strip() : un retour à la ligne final en plus
    # ne change rien pour le modèle, il ne doit pas créer de version.
    return text.strip()


class PromptStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_path = self.root / INDEX_FILE

    # --- lecture ---------------------------------------------------------

    def exists(self) -> bool:
        return self.index_path.is_file()

    def _read(self) -> dict:
        if not self.exists():
            return {}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def _prompt(self, index: dict, name: str) -> dict:
        if name not in index:
            known = ", ".join(sorted(index)) or "aucun"
            raise KeyError(f"prompt inconnu : {name} (connus : {known})")
        return index[name]

    def names(self) -> list[str]:
        return sorted(self._read())

    def active(self, name: str) -> str:
        return self._prompt(self._read(), name)["active"]

    def resolve(self, name: str, version: str) -> str:
        """Accepte `v2` ou `2` ; KeyError si la version n'existe pas."""
        entry = self._prompt(self._read(), name)
        wanted = version if version.startswith("v") else f"v{version}"
        if wanted not in {v["id"] for v in entry["versions"]}:
            raise KeyError(f"version inconnue : {name} {version}")
        return wanted

    def _file(self, name: str, version_id: str) -> Path:
        return self.root / name / f"{version_id}.txt"

    def load(self, name: str, version: str | None = None) -> str:
        version_id = self.resolve(name, version) if version else self.active(name)
        return self._file(name, version_id).read_text(encoding="utf-8")

    def history(self, name: str) -> list[dict]:
        """Les versions, de la plus récente à la plus ancienne."""
        entry = self._prompt(self._read(), name)
        return [
            {
                "id": v["id"],
                "date": v["date"],
                "author": v["author"],
                "description": v["description"],
                "active": v["id"] == entry["active"],
            }
            for v in reversed(entry["versions"])
        ]

    def diff(self, name: str, old: str, new: str | None = None) -> str:
        old_id = self.resolve(name, old)
        new_id = self.resolve(name, new) if new else self.active(name)
        return "".join(
            difflib.unified_diff(
                (self.load(name, old_id) + "\n").splitlines(keepends=True),
                (self.load(name, new_id) + "\n").splitlines(keepends=True),
                fromfile=f"{name} {old_id}",
                tofile=f"{name} {new_id}",
            )
        )

    # --- écriture --------------------------------------------------------

    def _write(self, index: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.index_path)

    def save(self, name: str, text: str, description: str, author: str,
             date: str | None = None) -> str:
        """Range `text` comme nouvelle version ; ne déplace pas le marque-page.

        La première version d'un prompt devient active : sans elle, l'agent
        n'aurait rien à lire. ValueError si ce texte est déjà rangé.
        """
        text = _normalize(text)
        index = self._read()
        entry = index.setdefault(name, {"active": None, "versions": []})
        digest = _sha256(text)
        for v in entry["versions"]:
            if v["sha256"] == digest:
                raise ValueError(f"texte identique à {name} {v['id']} : aucune version créée")

        version_id = f"v{len(entry['versions']) + 1}"
        path = self._file(name, version_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        entry["versions"].append({
            "id": version_id,
            "date": date or Date.today().isoformat(),
            "author": author,
            "description": description,
            "sha256": digest,
        })
        if entry["active"] is None:
            entry["active"] = version_id
        self._write(index)
        return version_id

    def use(self, name: str, version: str) -> str:
        """Déplace le marque-page ; le prochain lancement de `sensai` lit cette version."""
        version_id = self.resolve(name, version)
        index = self._read()
        index[name]["active"] = version_id
        self._write(index)
        return version_id

    # --- cohérence -------------------------------------------------------

    def check(self) -> list[str]:
        """Liste les problèmes du registre ; vide s'il est cohérent."""
        problems = []
        for name, entry in sorted(self._read().items()):
            ids = [v["id"] for v in entry["versions"]]
            for dup in sorted({i for i in ids if ids.count(i) > 1}):
                problems.append(f"{name} {dup} : numéro en double (fusion de deux branches ?)")
            if entry["active"] not in ids:
                problems.append(f"{name} : le marque-page pointe vers {entry['active']}, "
                                "qui n'existe pas")
            for v in entry["versions"]:
                path = self._file(name, v["id"])
                if not path.is_file():
                    problems.append(f"{name} {v['id']} : fichier {path} manquant")
                elif _sha256(path.read_text(encoding="utf-8")) != v["sha256"]:
                    problems.append(f"{name} {v['id']} : modifiée après avoir été rangée "
                                    "(ranger une nouvelle version à la place)")
        return problems
