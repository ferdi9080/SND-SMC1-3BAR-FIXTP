# Menggunakan image Python versi slim agar ringan
FROM python:3.10-slim

# Konfigurasi environment variables
ENV TZ=Asia/Jakarta \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install dependency sistem yang dibutuhkan (seperti compiler untuk matplotlib/numpy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set folder kerja di dalam container Docker
WORKDIR /app

# Copy requirement file
COPY requirements.txt /app/

# Install library dari requirements.txt dan juga tradingview-datafeed
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir tradingview-datafeed

# Copy semua file project lainnya ke dalam container
COPY . /app/

# Pastikan folder charts ada agar bot bisa save gambar tanpa error
RUN mkdir -p /app/charts

# Perintah utama untuk menjalankan aplikasi
CMD ["python", "tradingview_signal_bot.py"]
