FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY forwardbot ./forwardbot
COPY prompts ./prompts

RUN python -m pip install --upgrade pip && \
    python -m pip install .

CMD ["python", "-m", "forwardbot.main"]

