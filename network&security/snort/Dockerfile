FROM python:3.12-slim

WORKDIR /app

COPY generate.py /app/generate.py

ENV SNORT_TARGET=logstash
ENV SNORT_PORT=514
ENV SNORT_INTERVAL=2
ENV SNORT_ALERTS_PER_BURST=1
ENV SNORT_FORMAT=fast
ENV SNORT_HOSTNAME=snort-demo

CMD ["python", "-u", "/app/generate.py"]
