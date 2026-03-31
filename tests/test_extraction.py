from types import SimpleNamespace

from forwardbot.extraction import message_to_incoming_post
from forwardbot.models import MediaKind


def test_video_without_supports_streaming_attribute_is_supported() -> None:
    message = SimpleNamespace(
        photo=None,
        video=SimpleNamespace(file_id="video-file-id"),
        text=None,
        caption="Test caption",
        media_group_id=None,
        chat=SimpleNamespace(id=123),
        from_user=SimpleNamespace(id=456),
        forward_origin=None,
        message_id=42,
    )

    post = message_to_incoming_post(message)

    assert post.media_items[0].kind is MediaKind.VIDEO
    assert post.media_items[0].supports_streaming is False
