"""Conversation history management (context sent to the model)."""
from dataclasses import dataclass, field


@dataclass
class History:
    system_prompt: str = ""
    turns: list[dict] = field(default_factory=list)

    def as_messages(self) -> list[dict]:
        """List of messages to send to Ollama, system prompt first."""
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
        """Remove the last turn (used when a call fails midway)."""
        if self.turns:
            self.turns.pop()
