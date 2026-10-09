ARG BUILD_FROM
FROM python:3.12-alpine

RUN pip install --no-cache-dir requests==2.32.3 websocket-client==1.8.0

COPY app /app

CMD ["python3", "-u", "/app/main.py"]
