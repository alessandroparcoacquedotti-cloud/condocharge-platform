FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir -e ".[dev]"

COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY start_public_demo.py /app/start_public_demo.py

EXPOSE 8000

CMD ["python", "start_public_demo.py"]
