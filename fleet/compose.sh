#!/usr/bin/env bash
# Local fleet stack (Redpanda, ClickHouse, Grafana) on Docker compose.
#
#   fleet/compose.sh up [service...]   start the named services (default: all) and wait until healthy
#   fleet/compose.sh down              stop and remove the containers (the named volumes, i.e. the data, are kept)
#   fleet/compose.sh reset             down, then DELETE the volumes fleet_redpanda/_clickhouse/_grafana (all data)
#   fleet/compose.sh status            container state and the size of each fleet_* volume (8 GB data cap)
#
# Host ports: FLEET_KAFKA_PORT (19092), FLEET_CLICKHOUSE_PORT (18123), FLEET_GRAFANA_PORT (13000).
# Memory caps (docker-compose.yml): redpanda 1.5g, clickhouse 3g, grafana 512m. Run it directly, never `sh`.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose=(docker compose -f "$here/docker-compose.yml")
volumes=(fleet_redpanda fleet_clickhouse fleet_grafana)

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

[ $# -ge 1 ] || usage
cmd="$1"
shift

case "$cmd" in
  up)
    "${compose[@]}" up -d --wait "$@"
    ;;
  down)
    "${compose[@]}" down --remove-orphans
    ;;
  reset)
    "${compose[@]}" down --remove-orphans
    for v in "${volumes[@]}"; do
      if docker volume inspect "$v" >/dev/null 2>&1; then
        docker volume rm "$v" >/dev/null
        echo "removed volume $v"
      fi
    done
    ;;
  status)
    "${compose[@]}" ps
    pattern="$(IFS="|"; echo "${volumes[*]}")"
    docker system df -v | awk -v pat="^($pattern) " '/^VOLUME NAME/ {print; next} $0 ~ pat {print}'
    ;;
  *)
    usage
    ;;
esac
