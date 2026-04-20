from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from forwardbot.models import IncomingPost, RewriteResult


@dataclass(frozen=True, slots=True)
class CachedDraft:
    draft_id: str
    sender_user_id: int
    chat_id: int
    message_id: int
    incoming: IncomingPost
    current_result: RewriteResult
    created_at: datetime
    edit_mode: str = "text"
    headline_variants: tuple[str, ...] = ()


class DraftCache:
    def __init__(self, ttl_seconds: int = 7200, max_size: int = 500) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_size = max_size
        self._items: OrderedDict[str, CachedDraft] = OrderedDict()

    def put(self, cached: CachedDraft) -> None:
        self._gc()
        self._items.pop(cached.draft_id, None)
        self._items[cached.draft_id] = cached
        self._trim_to_max_size()

    def get(self, draft_id: str) -> CachedDraft | None:
        self._gc()
        return self._items.get(draft_id)

    def update(self, draft_id: str, new_result: RewriteResult) -> None:
        cached = self.get(draft_id)
        if cached is None:
            return
        self._items[draft_id] = replace(cached, current_result=new_result)

    def set_headline_variants(self, draft_id: str, variants: list[str] | tuple[str, ...]) -> None:
        cached = self.get(draft_id)
        if cached is None:
            return
        self._items[draft_id] = replace(cached, headline_variants=tuple(variants))

    def clear_headline_variants(self, draft_id: str) -> None:
        self.set_headline_variants(draft_id, ())

    def _gc(self) -> None:
        if not self._items:
            return
        cutoff = datetime.now(timezone.utc) - self._ttl
        expired_ids = [draft_id for draft_id, item in self._items.items() if item.created_at < cutoff]
        for draft_id in expired_ids:
            self._items.pop(draft_id, None)

    def _trim_to_max_size(self) -> None:
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)
