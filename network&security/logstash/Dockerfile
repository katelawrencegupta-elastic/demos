FROM docker.elastic.co/logstash/logstash:8.17.4

USER root
RUN /usr/share/logstash/bin/logstash-plugin install --no-verify logstash-codec-netflow \
    && mkdir -p /usr/share/logstash/data/queue \
    && chown -R logstash:logstash /usr/share/logstash/data
USER logstash

COPY config/logstash.yml /usr/share/logstash/config/logstash.yml
COPY config/pipelines.yml /usr/share/logstash/config/pipelines.yml
COPY pipeline/ /usr/share/logstash/pipeline/

VOLUME ["/usr/share/logstash/data/queue"]

# NetFlow (UDP 2055), Packetbeat/Beats (TCP 5044), Syslog (UDP/TCP 514)
EXPOSE 2055/udp 5044/tcp 514/udp 514/tcp
