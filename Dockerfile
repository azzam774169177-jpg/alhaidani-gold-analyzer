FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY photo_chart_analyzer.py telegram_photo_bot.py ./
CMD ["python", "-u", "telegram_photo_bot.py"]
