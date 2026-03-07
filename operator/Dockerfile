FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    kopf>=1.37.0 \
    kubernetes-asyncio>=31.0.0

COPY handler.py /app/handler.py

ENTRYPOINT ["kopf", "run", "/app/handler.py", "--verbose"]
