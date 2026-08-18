FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl wget \
    && rm -rf /var/lib/apt/lists/*

COPY receiver.py generate.py /app/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV EXFIL_OUTPUT_MODE=all
ENV EXFIL_SYSLOG_TARGET=logstash
ENV EXFIL_SYSLOG_PORT=514
ENV EXFIL_NETFLOW_TARGET=logstash
ENV EXFIL_NETFLOW_PORT=2055
ENV EXFIL_RECEIVER_URL=http://127.0.0.1:8888/upload
ENV EXFIL_INTERVAL=15
ENV EXFIL_JITTER=0.2
ENV EXFIL_SNORT_FORMAT=fast
ENV EXFIL_HOSTNAME=exfil-demo
ENV EXFIL_ALERT_PROBABILITY=0.4
ENV EXFIL_HOSTS=2
ENV EXFIL_TOOLS=curl,wget

EXPOSE 8888

ENTRYPOINT ["/app/entrypoint.sh"]
