from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from forwardbot.approved_store import ApprovedStore


@dataclass(frozen=True, slots=True)
class StyleContext:
    rules: str
    examples: str
    approved_examples: str = ""


class StyleRepository:
    def __init__(
        self,
        rules_path: Path,
        examples_path: Path,
        *,
        approved_store: ApprovedStore | None = None,
        approved_limit: int | None = None,
    ) -> None:
        self._rules_path = rules_path
        self._examples_path = examples_path
        self._approved_store = approved_store
        self._approved_limit = approved_limit

    def load(self) -> StyleContext:
        approved_examples = ""
        if self._approved_store is not None:
            approved_examples = self._approved_store.render_for_prompt(limit=self._approved_limit)
        return StyleContext(
            rules=self._read(self._rules_path),
            examples=self._read(self._examples_path),
            approved_examples=approved_examples,
        )

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()
