#!/bin/bash
# authentik_metrics.sh: push the health of one Authentik node to a Prometheus Pushgateway.
#
# Run it every minute on EACH node of a Docker-based Authentik deployment (single node or HA with a
# PostgreSQL primary/standbys and a keepalived VIP). It is read-only: it runs pg_isready and a few SELECTs inside
# the PostgreSQL container, `docker inspect`, `ip addr` and one `curl` against the local Authentik web port.
# Nothing is changed on the node. See contrib/README.md for installation and the metrics it produces.
#
#   authentik_metrics.sh              push to the Pushgateway
#   authentik_metrics.sh --dry-run    print what would be pushed
#
# Settings come from the environment or from /etc/default/netdisplay-authentik (shell syntax, optional).
# They all start with AK_ so they can't be hijacked by variables other tools set (NODE_NAME, PG_USER...):
#
#   AK_PUSHGATEWAY        Pushgateway base URL                        (default http://localhost:9091)
#   AK_VIP                keepalived VIP, e.g. 192.168.1.110; leave empty if you have none, and the
#                         authentik_node_vip_holder metric is simply not produced
#   AK_NODE_NAME          value of the `instance` label               (default: the hostname)
#   AK_PG_CONTAINER       PostgreSQL container name                   (default postgresql)
#   AK_PG_USER, AK_PG_DB  database role and name                      (default authentik, authentik)
#   AK_SERVER_CONTAINER   Authentik server container                  (default authentik-server)
#   AK_WORKER_CONTAINER   Authentik worker container                  (default authentik-worker)
#   AK_LDAP_FILTER        `docker ps --filter name=` match for an LDAP outpost; empty = you have none
#                                                                     (default ak-outpost-ldap)
#   AK_WEB_READY_URL      any 2xx from here means ready               (default http://localhost:9000/-/health/ready/)
set -u

[ -r /etc/default/netdisplay-authentik ] && . /etc/default/netdisplay-authentik

AK_PUSHGATEWAY="${AK_PUSHGATEWAY:-http://localhost:9091}"
AK_VIP="${AK_VIP:-}"
AK_NODE_NAME="${AK_NODE_NAME:-$(hostname)}"
AK_PG_CONTAINER="${AK_PG_CONTAINER:-postgresql}"
AK_PG_USER="${AK_PG_USER:-authentik}"
AK_PG_DB="${AK_PG_DB:-authentik}"
AK_SERVER_CONTAINER="${AK_SERVER_CONTAINER:-authentik-server}"
AK_WORKER_CONTAINER="${AK_WORKER_CONTAINER:-authentik-worker}"
AK_LDAP_FILTER="${AK_LDAP_FILTER-ak-outpost-ldap}"
AK_WEB_READY_URL="${AK_WEB_READY_URL:-http://localhost:9000/-/health/ready/}"

psql_q() { docker exec -u postgres "$AK_PG_CONTAINER" psql -U "$AK_PG_USER" -d "$AK_PG_DB" -tAc "$1" 2>/dev/null; }
healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = healthy ] && echo 1 || echo 0; }

out=""
add() { out+="$1"$'\n'; }

# --- which node holds the VIP
if [ -n "$AK_VIP" ]; then
    vip=0; ip addr show 2>/dev/null | grep -q "$AK_VIP" && vip=1
    add "# TYPE authentik_node_vip_holder gauge"
    add "authentik_node_vip_holder $vip"
fi

# --- database: up, primary or standby, replication
db_up=0; docker exec "$AK_PG_CONTAINER" pg_isready -U "$AK_PG_USER" >/dev/null 2>&1 && db_up=1
add "# TYPE authentik_db_up gauge"
add "authentik_db_up $db_up"

case "$(psql_q "SELECT pg_is_in_recovery();")" in
    f)  # primary: how many standbys are streaming
        add "authentik_db_primary 1"
        add "authentik_db_replicas_streaming $(psql_q "SELECT count(*) FROM pg_stat_replication WHERE state='streaming';" || echo 0)"
        ;;
    t)  # standby: is it receiving WAL, and how far behind is replay (bytes)
        add "authentik_db_primary 0"
        add "authentik_db_receiving $(psql_q "SELECT count(*) FROM pg_stat_wal_receiver WHERE status='streaming';" || echo 0)"
        add "authentik_db_replay_backlog_bytes $(psql_q "SELECT COALESCE(pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn()),0)::bigint;" || echo 0)"
        ;;
esac
conns=$(psql_q "SELECT count(*) FROM pg_stat_activity;")
[ -n "$conns" ] && add "authentik_db_connections $conns"

# --- containers (Docker health status == healthy)
add "# TYPE authentik_container_up gauge"
add "authentik_container_up{container=\"authentik-server\"} $(healthy "$AK_SERVER_CONTAINER")"
add "authentik_container_up{container=\"authentik-worker\"} $(healthy "$AK_WORKER_CONTAINER")"
add "authentik_container_up{container=\"postgresql\"} $(healthy "$AK_PG_CONTAINER")"
if [ -n "$AK_LDAP_FILTER" ]; then
    ldap=$(docker ps --filter "name=$AK_LDAP_FILTER" --format '{{.Names}}' | head -1)
    add "authentik_container_up{container=\"ldap-outpost\"} $([ -n "$ldap" ] && healthy "$ldap" || echo 0)"
fi

# --- web
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$AK_WEB_READY_URL")
case "$code" in 2??) ready=1 ;; *) ready=0 ;; esac
add "authentik_web_ready $ready"

version=$(docker inspect -f '{{.Config.Image}}' "$AK_SERVER_CONTAINER" 2>/dev/null | sed 's/.*://')
add "authentik_info{version=\"${version:-unknown}\"} 1"
add "authentik_last_push_timestamp_seconds $(date +%s)"

if [ "${1:-}" = "--dry-run" ]; then
    echo "# instance=$AK_NODE_NAME pushgateway=$AK_PUSHGATEWAY"
    printf '%s' "$out"
else
    printf '%s' "$out" | curl -s -m 10 --data-binary @- "$AK_PUSHGATEWAY/metrics/job/authentik/instance/$AK_NODE_NAME"
fi
