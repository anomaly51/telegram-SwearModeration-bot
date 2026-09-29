FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.3.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

RUN pip install "poetry==$POETRY_VERSION"

WORKDIR /app

COPY pyproject.toml poetry.lock ./


RUN poetry install --no-root --no-ansi

COPY . .

ARG VCS_REF=""
ARG VCS_DATE=""
RUN python version_info.py --write --commit "$VCS_REF" --commit-date "$VCS_DATE"

CMD ["python", "app.py"]
