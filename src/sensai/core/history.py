"""Gestion de l'historique de conversation (contexte envoyé au modèle)."""
from dataclasses import dataclass, field


@dataclass
class History:
    system_prompt: str = ""
    turns: list[dict] = field(default_factory=list)

    def as_messages(self) -> list[dict]:
        """Liste de messages à envoyer à Ollama, prompt système en tête."""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.turns)
        return messages

    def add_user(self, content: str) -> None:
        self.turns.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.turns.append({"role": "assistant", "content": content})

    def drop_last(self) -> None:
        """Retire le dernier tour (utilisé quand un appel échoue en cours de route)."""
        if self.turns:
            self.turns.pop()
