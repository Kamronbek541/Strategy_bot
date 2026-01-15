# 1. Используем стабильный образ Debian Bullseye
FROM python:3.12-bullseye

# 2. Устанавливаем рабочую директорию
WORKDIR /app

# 3. Устанавливаем ВСЕ необходимые зависимости для OpenCV и Tesseract
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Зависимости для OpenCV
    libgl1 \
    libglib2.0-0 \
    # Зависимости для Tesseract
    tesseract-ocr \
    # Очистка
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 4. Копируем requirements.txt и устанавливаем Python-библиотеки
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем весь остальной код приложения
COPY . .

# 6. Команда по умолчанию для запуска
CMD ["python3", "bot.py"]
