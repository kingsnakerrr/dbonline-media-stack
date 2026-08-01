FROM python:3.12-alpine

WORKDIR /app
COPY autoremove.py /app/autoremove.py
COPY entrypoint.sh /app/entrypoint.sh

RUN addgroup -S app && adduser -S -G app app \
    && mkdir -p /data && chmod +x /app/entrypoint.sh && chown -R app:app /data /app

USER app
ENTRYPOINT ["/app/entrypoint.sh"]
