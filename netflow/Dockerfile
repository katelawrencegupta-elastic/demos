FROM python:3.12-slim

WORKDIR /app

COPY generate.py /app/generate.py

ENV NETFLOW_TARGET=172.17.0.2
ENV NETFLOW_PORT=2055
ENV NETFLOW_INTERVAL=1
ENV NETFLOW_FLOWS_PER_PACKET=8

CMD ["python", "-u", "/app/generate.py"]
