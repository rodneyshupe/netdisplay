# contrib

Optional helpers that feed netdisplay metrics it can't get from a standard exporter. Nothing here is needed to run netdisplay.

## authentik_metrics.sh

Pushes the health of one [Authentik](https://goauthentik.io) node to a Prometheus **Pushgateway**, so the
[Authentik page snippet](../examples/snippets/authentik-ha.yaml) can show which node is the master of a high-availability
cluster and whether everything is healthy. It works for a single node too, and for HA setups using a PostgreSQL
primary with standbys and a keepalived VIP.

These are **not** Authentik's own Prometheus metrics; they describe the Docker deployment around it, and Authentik doesn't
expose any of this.

### What it checks

Run on each node, once a minute. It is **read-only**: `pg_isready` and a few `SELECT`s inside the PostgreSQL container,
`docker inspect`, `ip addr`, and one `curl` to the local Authentik web port. Nothing on the node is changed.

| Metric | Meaning |
|---|---|
| `authentik_node_vip_holder` | `1` on the node holding the keepalived VIP (omitted if `AK_VIP` is empty) |
| `authentik_db_up` | PostgreSQL answers `pg_isready` |
| `authentik_db_primary` | `1` on the primary, `0` on a standby (`pg_is_in_recovery()`) |
| `authentik_db_replicas_streaming` | primary only: standbys currently streaming |
| `authentik_db_receiving` | standby only: `1` if it is receiving WAL |
| `authentik_db_replay_backlog_bytes` | standby only: WAL received but not yet replayed |
| `authentik_db_connections` | open connections |
| `authentik_container_up{container=...}` | `1` when Docker reports the container healthy: `authentik-server`, `authentik-worker`, `postgresql`, `ldap-outpost` |
| `authentik_web_ready` | any 2xx from `/-/health/ready/` |
| `authentik_info{version=...}` | image tag of the server container |
| `authentik_last_push_timestamp_seconds` | when this node last reported, for staleness checks |

All series are pushed under job `authentik`, with `instance=<node name>`.

### Requirements

- Docker on the node, with the container names below (or set them, see the settings).
- A **Pushgateway** reachable from the node, and your Prometheus/VictoriaMetrics scraping it **with `honor_labels: true`**
  (otherwise the job and instance labels are overwritten and the page can't tell the nodes apart):

  ```yaml
  - job_name: pushgateway
    honor_labels: true
    static_configs:
      - targets: ['192.168.1.10:9091']
  ```
- `bash`, `curl`, `ip` (iproute2) on the node.
- The script needs permission to run `docker exec`, so run it as root (or a user in the `docker` group).

### Install (on each node)

1. **Try it without pushing anything:**

   ```bash
   AK_VIP=192.168.1.110 ./authentik_metrics.sh --dry-run
   ```

   It prints the metrics it would push. Check the container names and that nothing reads `0` that shouldn't.

2. **Put it in place and give it settings:**

   ```bash
   sudo install -m 755 authentik_metrics.sh /usr/local/bin/authentik_metrics.sh
   sudo tee /etc/default/netdisplay-authentik >/dev/null <<'EOF'
   AK_PUSHGATEWAY=http://192.168.1.10:9091
   AK_VIP=192.168.1.110
   EOF
   ```

3. **Run it every minute** from root's crontab (`sudo crontab -e`):

   ```
   * * * * * /usr/local/bin/authentik_metrics.sh >/dev/null 2>&1
   ```

4. **Check** that the three nodes appear: `curl -s http://192.168.1.10:9091/metrics | grep authentik_last_push`.

To remove it: delete the crontab line, `/usr/local/bin/authentik_metrics.sh` and `/etc/default/netdisplay-authentik`.

### Settings

Environment variables, or `/etc/default/netdisplay-authentik` in shell syntax. All start with `AK_` on purpose, so they can't
be hijacked by variables that are already set on the host (a bare `NODE_NAME` was set on one of the test nodes and silently overrode the hostname).

| Variable | Default | Meaning |
|---|---|---|
| `AK_PUSHGATEWAY` | `http://localhost:9091` | Pushgateway base URL |
| `AK_VIP` | *(empty)* | keepalived VIP; empty means the VIP metric is not produced |
| `AK_NODE_NAME` | the hostname | `instance` label value |
| `AK_PG_CONTAINER` | `postgresql` | PostgreSQL container |
| `AK_PG_USER`, `AK_PG_DB` | `authentik`, `authentik` | database role and name |
| `AK_SERVER_CONTAINER` | `authentik-server` | server container |
| `AK_WORKER_CONTAINER` | `authentik-worker` | worker container |
| `AK_LDAP_FILTER` | `ak-outpost-ldap` | `docker ps --filter name=` match for an LDAP outpost; set empty if you have none |
| `AK_WEB_READY_URL` | `http://localhost:9000/-/health/ready/` | readiness URL; any 2xx counts |

### Things to know

- **Pushgateway keeps the last value forever.** If a node dies or stops running the script its series stay, looking
  healthy. That's why every push carries `authentik_last_push_timestamp_seconds`, and why the snippet's alert and node dot
  treat anything older than 3 minutes as stale. A node that never pushed at all won't appear; the page's "nodes reporting"
  check (`ak_nodes` in the snippet) catches that.
- **Replacing a node** leaves the old node's series in the Pushgateway until you delete the group:
  `curl -X DELETE http://192.168.1.10:9091/metrics/job/authentik/instance/<old name>`.
- **Authentik's own metrics** (HTTP latency, worker tasks) are separate; see Authentik's documentation for exposing them. This script does not
  replace those; it answers "which node is the master and is the cluster healthy".
- It has been tested against Authentik 2026.8 in the Docker Compose layout (`authentik-server`, `authentik-worker`,
  `postgresql`, an LDAP outpost). If your containers are named differently, set the `AK_*` names above.
