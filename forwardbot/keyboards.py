from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def build_draft_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Neue Headline", callback_data=f"d:nh:{draft_id}")
    builder.button(text="♻️ Neu schreiben", callback_data=f"d:rg:{draft_id}")
    builder.button(text="✂️ Kürzer", callback_data=f"d:sh:{draft_id}")
    builder.button(text="📝 Länger", callback_data=f"d:lg:{draft_id}")
    builder.button(text="🎯 Sachlicher", callback_data=f"d:fc:{draft_id}")
    builder.button(text="🔥 Emotionaler", callback_data=f"d:em:{draft_id}")
    builder.button(text="✅ Passt", callback_data=f"d:ok:{draft_id}")
    builder.button(text="👎", callback_data=f"d:no:{draft_id}")
    builder.adjust(2, 2, 2, 2)
    return builder.as_markup()


def build_headline_picker(draft_id: str, variants: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, variant in enumerate(variants[:3]):
        builder.button(text=variant, callback_data=f"d:nhP:{draft_id}:{index}")
    builder.button(text="⬅️ Zurück", callback_data=f"d:bk:{draft_id}")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def parse_callback(data: str) -> tuple[str, str, str | None]:
    parts = data.split(":", maxsplit=3)
    if len(parts) < 3 or parts[0] != "d":
        raise ValueError("Unsupported callback payload.")
    action = parts[1]
    draft_id = parts[2]
    arg = parts[3] if len(parts) == 4 else None
    return action, draft_id, arg
