#!/usr/bin/env bash
set -euo pipefail

echo "Starting protocol servers..." >&2

cp /etc/packetbeat-demo/nginx.conf /etc/nginx/sites-available/default
ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default

mkdir -p /var/run/mysqld /var/lib/mysql
chown -R mysql:mysql /var/lib/mysql /var/run/mysqld

if [ ! -d /var/lib/mysql/mysql ]; then
  mariadb-install-db --user=mysql --datadir=/var/lib/mysql >/dev/null
fi
mysqld_safe --datadir=/var/lib/mysql --bind-address=127.0.0.1 &
sleep 3
mariadb -uroot -e "CREATE USER IF NOT EXISTS 'demo'@'127.0.0.1' IDENTIFIED BY 'demo'; GRANT ALL ON *.* TO 'demo'@'127.0.0.1'; FLUSH PRIVILEGES;" 2>/dev/null || true

PG_VERSION="$(ls /etc/postgresql)"
su - postgres -c "pg_ctlcluster ${PG_VERSION} main start"
su - postgres -c "psql -v ON_ERROR_STOP=1 -c \"CREATE USER demo WITH PASSWORD 'demo';\"" 2>/dev/null \
  || su - postgres -c "psql -v ON_ERROR_STOP=1 -c \"ALTER USER demo WITH PASSWORD 'demo';\""
su - postgres -c "psql -v ON_ERROR_STOP=1 -c \"CREATE DATABASE demo OWNER demo;\"" 2>/dev/null || true

redis-server --bind 127.0.0.1 --daemonize yes
memcached -u memcache -l 127.0.0.1 -d

rabbitmq-server -detached

mkdir -p /var/lib/mongodb
mongod --bind_ip 127.0.0.1 --dbpath /var/lib/mongodb --fork --logpath /var/log/mongodb.log

export MAX_HEAP_SIZE=256M
export HEAP_NEWSIZE=64M
sed -i 's/^rpc_address:.*/rpc_address: 127.0.0.1/' /etc/cassandra/cassandra.yaml
sed -i 's/^listen_address:.*/listen_address: 127.0.0.1/' /etc/cassandra/cassandra.yaml
sed -i 's/^native_transport_port:.*/native_transport_port: 9042/' /etc/cassandra/cassandra.yaml
cassandra -R -f >/var/log/cassandra.log 2>&1 &

echo "/srv/nfs *(rw,sync,no_subtree_check,insecure,no_root_squash)" > /etc/exports
echo "packetbeat demo file" > /srv/nfs/hello.txt
service rpcbind start || true
service nfs-kernel-server start || true
exportfs -ra 2>/dev/null || echo "Warning: NFS export unavailable; NFS traffic may be limited." >&2

dnsmasq --conf-file=/etc/packetbeat-demo/dnsmasq.conf --keep-in-foreground >/var/log/dnsmasq.log 2>&1 &
nginx

python3 /usr/local/bin/thrift_server.py >/var/log/thrift.log 2>&1 &
python3 /usr/local/bin/sip_responder.py >/var/log/sip.log 2>&1 &

echo "Protocol servers started." >&2
