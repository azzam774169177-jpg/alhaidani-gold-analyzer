FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY telegram_photo_bot.py ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "-u", "telegram_photo_bot.py"]
