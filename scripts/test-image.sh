#!/usr/bin/env bash
# Pull the newly pushed image and run a date-named test copy of May.
#
# Usage:
#   ./scripts/test-image.sh [tag] [port]     # default: dev 5052
#   ./scripts/test-image.sh latest
#   ./scripts/test-image.sh --down           # tear down ALL test instances
#
# Each run creates:
#   container:  may-test-<YYYYMMDD-HHMM>
#   project:    may-test-<YYYYMMDD-HHMM>  (own isolated data volume)
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE_FILE="docker-compose.test.yml"
PREFIX="may-test"

if [[ "${1:-}" == "--down" ]]; then
  mapfile -t projects < <(docker compose ls --all --format '{{.Name}}' 2>/dev/null | grep "^${PREFIX}-" || true)
  if [[ ${#projects[@]} -eq 0 ]]; then
    echo "No ${PREFIX}-* instances found."
    exit 0
  fi
  for p in "${projects[@]}"; do
    echo "Removing ${p}..."
    docker compose -p "$p" -f "$COMPOSE_FILE" down -v
  done
  exit 0
fi

TAG="${1:-dev}"
PORT="${2:-5052}"
STAMP="$(date +%Y%m%d-%H%M)"
NAME="${PREFIX}-${STAMP}"

export MAY_TEST_NAME="$NAME"
export MAY_TEST_TAG="$TAG"
export MAY_TEST_PORT="$PORT"

echo "==> Pulling ghcr.io/dannymcc/may:${TAG} and starting ${NAME} on port ${PORT}"
docker compose -p "$NAME" -f "$COMPOSE_FILE" up -d

echo "==> Waiting for health check..."
for i in $(seq 1 30); do
  if curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    echo "==> ${NAME} is healthy: http://localhost:${PORT}"
    echo "    Image: $(docker inspect --format '{{.Config.Image}} ({{.Image}})' "$NAME")"
    echo "    Admin password (if auto-generated): docker logs ${NAME} | grep -i password"
    echo "    Tear down: ./scripts/test-image.sh --down"
    exit 0
  fi
  sleep 2
done

echo "!! ${NAME} did not become healthy in 60s. Logs:"
docker logs --tail 50 "$NAME"
exit 1
