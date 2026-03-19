FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl \
    tar \
    gzip \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://github.com/rclone/rclone/releases/latest/download/rclone-current-linux-amd64.zip" -o /tmp/rclone.zip \
    && unzip /tmp/rclone.zip -d /tmp/rclone \
    && mv /tmp/rclone/rclone-*-linux-amd64/rclone /usr/local/bin/rclone \
    && chmod +x /usr/local/bin/rclone \
    && rm -rf /tmp/rclone /tmp/rclone.zip

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data /tmp/baumlabbackup

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
