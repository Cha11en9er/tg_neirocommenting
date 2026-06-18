FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY prod/ prod/
COPY test/ test/

# Команда переопределяется в docker-compose (prod или test)
CMD ["python", "test/neuro_commenter_test.py"]
