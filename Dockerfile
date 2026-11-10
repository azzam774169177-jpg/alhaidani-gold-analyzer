FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY photo_chart_analyzer.py telegram_photo_bot.py telegram_webhook_app.py ./
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --threads 4 --timeout 60 telegram_webhook_app:app"]
