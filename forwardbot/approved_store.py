from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApprovedExample:
    title: str
    paragraphs: list[str]
    source_hint: str | None
    approved_at: datetime


class ApprovedStore:
    def __init__(self, path: Path, max_examples: int = 30) -> None:
        self._path = path
        self._max_examples = max_examples

    def add(self, example: ApprovedExample) -> None:
        examples = self.load_all()
        examples.append(example)
        examples = examples[-self._max_examples :]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = []
        for item in examples:
            raw = asdict(item)
            raw["approved_at"] = item.approved_at.astimezone(timezone.utc).isoformat()
            payload.append(json.dumps(raw, ensure_ascii=False))
        self._path.write_text("\n".join(payload) + ("\n" if payload else ""), encoding="utf-8")

    def load_all(self) -> list[ApprovedExample]:
        if not self._path.exists():
            return []
        rows: list[ApprovedExample] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            rows.append(
                ApprovedExample(
                    title=str(raw["title"]),
                    paragraphs=[str(item) for item in raw["paragraphs"]],
                    source_hint=raw.get("source_hint"),
                    approved_at=datetime.fromisoformat(str(raw["approved_at"])),
                )
            )
        return rows

    def render_for_prompt(self, limit: int | None = None) -> str:
        examples = self.load_all()
        if limit is not None:
            examples = examples[-limit:]
        if not examples:
            return ""

        blocks: list[str] = []
        for example in examples:
            lines = ["### Beispiel", f"**Titel**: {example.title}"]
            if example.source_hint:
                lines.append(f"**Quelle**: {example.source_hint}")
            lines.extend(example.paragraphs)
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)
