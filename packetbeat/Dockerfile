FROM ubuntu:22.04

ARG TARGETARCH
ARG PACKETBEAT_VERSION=8.17.4

ENV DEBIAN_FRONTEND=noninteractive \
    LOGSTASH_HOST=172.17.0.2 \
    LOGSTASH_PORT=5044 \
    TRAFFIC_INTERVAL=5

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    gettext-base \
    iputils-ping \
    dnsutils \
    netcat-openbsd \
    iproute2 \
    nginx \
    dnsmasq \
    redis-server \
    mariadb-server \
    postgresql \
    postgresql-contrib \
    memcached \
    rabbitmq-server \
    nfs-kernel-server \
    nfs-common \
    rpcbind \
    python3 \
    python3-pip \
    python3-six \
    python3-dev \
    thrift-compiler \
    libthrift-dev \
    python3-thrift \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# MongoDB 7.0
RUN curl -fsSL https://pgp.mongodb.com/server-7.0.asc \
    | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg \
    && echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
    > /etc/apt/sources.list.d/mongodb-org-7.0.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends mongodb-org \
    && rm -rf /var/lib/apt/lists/*

# Apache Cassandra 4.1
RUN curl -fsSL https://downloads.apache.org/cassandra/KEYS \
    | gpg --dearmor -o /usr/share/keyrings/cassandra.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cassandra.gpg] https://debian.cassandra.apache.org 41x main" \
    > /etc/apt/sources.list.d/cassandra.sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends cassandra \
    && rm -rf /var/lib/apt/lists/*

# Packetbeat (match container architecture)
RUN case "${TARGETARCH}" in \
      amd64) PB_ARCH=amd64 ;; \
      arm64) PB_ARCH=arm64 ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/packetbeat.deb \
      "https://artifacts.elastic.co/downloads/beats/packetbeat/packetbeat-${PACKETBEAT_VERSION}-${PB_ARCH}.deb" \
    && dpkg -i /tmp/packetbeat.deb \
    && rm /tmp/packetbeat.deb

RUN pip3 install --no-cache-dir \
    pika \
    pymongo \
    cassandra-driver \
    redis \
    psycopg2-binary \
    mysql-connector-python \
    python-memcached

WORKDIR /app

COPY config/ /etc/packetbeat-demo/
COPY thrift/ /app/thrift/
COPY scripts/ /usr/local/bin/

RUN mkdir -p /app/thrift/gen \
    && thrift --gen py -out /app/thrift/gen /app/thrift/ping.thrift \
    && openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/ssl/private/packetbeat-demo.key \
    -out /etc/ssl/certs/packetbeat-demo.crt \
    -subj "/CN=localhost" \
    && mkdir -p /srv/nfs /mnt/nfs /var/run/postgresql \
    && chmod +x /usr/local/bin/*.sh /usr/local/bin/*.py

COPY packetbeat.yml.template /etc/packetbeat/packetbeat.yml.template

EXPOSE 5044

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
