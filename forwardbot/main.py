from __future__ import annotations

import asyncio
import logging

from forwardbot.bot import ForwardBotApp
from forwardbot.config import SettingsError, load_settings


def main() -> None:
    try:
        settings = load_settings()
    except SettingsError as exc:
        raise SystemExit(str(exc)) from exc

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = ForwardBotApp(settings)

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Shutdown requested by user.")
    finally:
        asyncio.run(app.shutdown())


if __name__ == "__main__":
    main()
