#!/usr/bin/env bash
# Local fleet stack (Redpanda, ClickHouse, Grafana) on Docker compose.
#
#   fleet/compose.sh up [service...]   start the named services (default: all) and wait until healthy
#   fleet/compose.sh down              stop and remove the containers (data in fleet/data/volumes/ is kept)
#   fleet/compose.sh reset             down, then DELETE fleet/data/volumes/ (all stored data)
#   fleet/compose.sh status            container state
#
# Host ports: FLEET_KAFKA_PORT (19092), FLEET_CLICKHOUSE_PORT (18123), FLEET_GRAFANA_PORT (13000).
# Memory caps (docker-compose.yml): redpanda 1.5g, clickhouse 3g, grafana 512m. Run it directly, never `sh`.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose=(docker compose -f "$here/docker-compose.yml")
volumes="$here/data/volumes"

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

[ $# -ge 1 ] || usage
cmd="$1"
shift

case "$cmd" in
  up)
    mkdir -p "$volumes/redpanda" "$volumes/clickhouse" "$volumes/grafana"
    "${compose[@]}" up -d --wait "$@"
    ;;
  down)
    "${compose[@]}" down --remove-orphans
    ;;
  reset)
    "${compose[@]}" down --remove-orphans
    rm -rf "$volumes"
    echo "removed $volumes"
    ;;
  status)
    "${compose[@]}" ps
    ;;
  *)
    usage
    ;;
esac
