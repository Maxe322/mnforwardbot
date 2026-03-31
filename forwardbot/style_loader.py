from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StyleContext:
    rules: str
    examples: str


class StyleRepository:
    def __init__(self, rules_path: Path, examples_path: Path) -> None:
        self._rules_path = rules_path
        self._examples_path = examples_path

    def load(self) -> StyleContext:
        return StyleContext(
            rules=self._read(self._rules_path),
            examples=self._read(self._examples_path),
        )

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

