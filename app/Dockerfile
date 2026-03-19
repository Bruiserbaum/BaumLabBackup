FROM rclone/rclone:latest AS rclone

FROM python:3.12-slim

COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data /tmp/baumlabbackup

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
