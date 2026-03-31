# MN Forwardbot

Telegram bot for rewriting forwarded source posts into German draft posts while preserving the original Telegram media.

## Features

- Accepts text posts, single photo/video posts, and Telegram media groups
- Restricts usage to whitelisted Telegram user IDs
- Uses an OpenAI-compatible chat completion API for translation, condensation, and style adaptation
- Keeps footer/hashtags out of the generated draft because a downstream bot adds them later
- Reads style rules and example posts from editable files
- Runs locally or in Docker on a VPS

## Quick start

1. Copy `.env.example` to `.env` and fill in the values.
2. Edit `prompts/style_rules.md` and `prompts/style_examples.md`.
3. Install dependencies:

```bash
python -m pip install -e .[dev]
```

4. Start the bot:

```bash
python -m forwardbot.main
```

## Environment variables

- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_USER_IDS`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_DISABLE_THINKING` (optional, default `true` for Moonshot `kimi-k2.5`)
- `LLM_TEMPERATURE` (optional, default `0.6` for Moonshot `kimi-k2.5`, otherwise `0.2`)
- `LLM_TIMEOUT_SECONDS` (optional, default `45`)
- `LOG_LEVEL` (optional, default `INFO`)
- `ALBUM_COLLECT_WINDOW_SECONDS` (optional, default `1.2`)
- `TELEGRAM_CAPTION_LIMIT` (optional, default `950`)
- `TELEGRAM_MESSAGE_LIMIT` (optional, default `4000`)
- `STYLE_RULES_PATH` (optional)
- `STYLE_EXAMPLES_PATH` (optional)

## Project layout

- `forwardbot/`: bot code
- `prompts/style_rules.md`: editable style rules
- `prompts/style_examples.md`: editable example posts
- `tests/`: unit tests for core behavior

## Notes

- The MVP assumes source channels allow normal Telegram forwarding, including media.
- Media groups are buffered in memory and processed after a short debounce window.
- The bot returns a draft in the bot chat; it does not publish into the final channel.
