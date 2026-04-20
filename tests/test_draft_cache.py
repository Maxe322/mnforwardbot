from datetime import datetime, timedelta, timezone

from forwardbot.draft_cache import CachedDraft, DraftCache
from forwardbot.models import IncomingPost, RewriteResult


def _build_cached(draft_id: str, *, created_at: datetime | None = None) -> CachedDraft:
    return CachedDraft(
        draft_id=draft_id,
        sender_user_id=1,
        chat_id=1,
        message_id=100,
        incoming=IncomingPost(sender_user_id=1, chat_id=1, source_text="source"),
        current_result=RewriteResult(
            short_mode=False,
            title="Titel",
            paragraphs=("Absatz",),
            formatted_html="<b>Titel</b>\n\nAbsatz",
        ),
        created_at=created_at or datetime.now(timezone.utc),
    )


def test_put_and_get_roundtrip() -> None:
    cache = DraftCache()
    cached = _build_cached("abc123")

    cache.put(cached)

    assert cache.get("abc123") == cached


def test_ttl_expiry() -> None:
    cache = DraftCache(ttl_seconds=1)
    cached = _build_cached("expired", created_at=datetime.now(timezone.utc) - timedelta(seconds=10))

    cache.put(cached)

    assert cache.get("expired") is None


def test_max_size_evicts_oldest() -> None:
    cache = DraftCache(max_size=2)
    cache.put(_build_cached("one"))
    cache.put(_build_cached("two"))
    cache.put(_build_cached("three"))

    assert cache.get("one") is None
    assert cache.get("two") is not None
    assert cache.get("three") is not None
