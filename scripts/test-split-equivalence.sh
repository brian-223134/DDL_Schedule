#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 기본 fixture는 비결정적인 값(NOW, UUID 등)을 피해서 dump 비교가 안정적으로 동작하도록 구성한다.
BASELINE_SQL="$ROOT_DIR/tests/fixtures/equivalence_baseline.sql"
FORWARD_SQL="$ROOT_DIR/tests/fixtures/equivalence_forward.sql"
INCLUDE_MANUAL=0
ORIGINAL_DB="ddl_equivalence_original"
SPLIT_DB="ddl_equivalence_split"

usage() {
  cat <<'EOF'
Usage:
  scripts/test-split-equivalence.sh [options]

Options:
  --baseline PATH       Baseline schema/data SQL applied before migration.
  --forward PATH        Original forward migration SQL to compare with split output.
  --include-manual      Execute generated manual phase SQL too.
  -h, --help            Show this help.

Default fixtures:
  tests/fixtures/equivalence_baseline.sql
  tests/fixtures/equivalence_forward.sql
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline)
      BASELINE_SQL="$2"
      shift 2
      ;;
    --forward)
      FORWARD_SQL="$2"
      shift 2
      ;;
    --include-manual)
      INCLUDE_MANUAL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[error] unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# 사용자가 상대 경로를 넘겨도 이후 단계에서는 절대 경로로만 다루어 경로 기준을 고정한다.
BASELINE_SQL="$(cd "$(dirname "$BASELINE_SQL")" && pwd)/$(basename "$BASELINE_SQL")"
FORWARD_SQL="$(cd "$(dirname "$FORWARD_SQL")" && pwd)/$(basename "$FORWARD_SQL")"

if [[ ! -f "$BASELINE_SQL" ]]; then
  echo "[error] baseline SQL not found: $BASELINE_SQL" >&2
  exit 1
fi

if [[ ! -f "$FORWARD_SQL" ]]; then
  echo "[error] forward SQL not found: $FORWARD_SQL" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

MYSQL_SERVICE="mysql"
MYSQL_ROOT_PASSWORD="root"

# Python MySQL driver를 설치하지 않도록, 컨테이너 안의 mysql/mysqldump CLI를 그대로 사용한다.
MYSQL=(docker compose exec -T "$MYSQL_SERVICE" mysql -uroot "-p$MYSQL_ROOT_PASSWORD")
MYSQLDUMP=(docker compose exec -T "$MYSQL_SERVICE" mysqldump -uroot "-p$MYSQL_ROOT_PASSWORD")

wait_for_mysql() {
  local container_id
  container_id="$(docker compose ps -q "$MYSQL_SERVICE")"
  if [[ -z "$container_id" ]]; then
    echo "[error] mysql service is not running" >&2
    exit 1
  fi

  # Compose healthcheck가 healthy가 될 때까지 기다려 초기화 중 접속 실패를 피한다.
  for _ in {1..60}; do
    local status
    status="$(docker inspect -f '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)"
    if [[ "$status" == "healthy" ]]; then
      return 0
    fi
    sleep 2
  done

  echo "[error] mysql service did not become healthy in time" >&2
  docker compose ps "$MYSQL_SERVICE" >&2
  exit 1
}

run_sql_file() {
  local db_name="$1"
  local sql_file="$2"
  "${MYSQL[@]}" "$db_name" < "$sql_file"
}

reset_db() {
  local db_name="$1"
  "${MYSQL[@]}" -e "DROP DATABASE IF EXISTS \`$db_name\`; CREATE DATABASE \`$db_name\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
}

dump_db() {
  local db_name="$1"
  local out_file="$2"

  # AUTO_INCREMENT 값처럼 실행 순서와 무관한 dump 차이는 제거하고 최종 schema/data만 비교한다.
  "${MYSQLDUMP[@]}" \
    --single-transaction \
    --skip-comments \
    --compact \
    --skip-dump-date \
    --no-tablespaces \
    "$db_name" \
    | sed -E 's/ AUTO_INCREMENT=[0-9]+//g' > "$out_file"
}

run_split_phase_files() {
  local split_dir="$1"
  local base_name="$2"
  local phase

  for phase in pre data post manual; do
    local sql_file="$split_dir/$base_name.$phase.sql"
    if [[ ! -f "$sql_file" ]]; then
      continue
    fi

    if [[ "$phase" == "manual" && "$INCLUDE_MANUAL" -ne 1 ]]; then
      # manual phase는 자동 실행 대상이 아니므로, 검토 후 명시적으로 opt-in한 경우에만 실행한다.
      echo "[error] generated manual phase exists: $sql_file" >&2
      echo "[error] rerun with --include-manual only after reviewing it" >&2
      exit 2
    fi

    echo "[ok] executing split phase: $phase"
    run_sql_file "$SPLIT_DB" "$sql_file"
  done
}

cd "$ROOT_DIR"

# Docker Desktop이 꺼져 있으면 Compose 오류가 길게 나오므로, 먼저 짧은 메시지로 중단한다.
if ! docker info >/dev/null 2>&1; then
  echo "[error] Docker daemon is not reachable. Start Docker Desktop, then rerun this script." >&2
  exit 1
fi

echo "[ok] starting mysql service"
docker compose up -d "$MYSQL_SERVICE"
wait_for_mysql

echo "[ok] resetting comparison databases"
# 같은 baseline에서 시작하도록 비교용 DB 두 개를 매번 새로 만든다.
reset_db "$ORIGINAL_DB"
reset_db "$SPLIT_DB"

echo "[ok] applying baseline"
run_sql_file "$ORIGINAL_DB" "$BASELINE_SQL"
run_sql_file "$SPLIT_DB" "$BASELINE_SQL"

echo "[ok] applying original migration"
run_sql_file "$ORIGINAL_DB" "$FORWARD_SQL"

SPLIT_OUT_DIR="$TMP_DIR/split-output"
BASE_NAME="$(basename "$FORWARD_SQL" .sql)"

echo "[ok] generating split output"
python3 "$ROOT_DIR/production/migration_phase_splitter.py" \
  --forward "$FORWARD_SQL" \
  --out-dir "$SPLIT_OUT_DIR"

run_split_phase_files "$SPLIT_OUT_DIR" "$BASE_NAME"

echo "[ok] dumping final database states"
# 원본 migration 경로와 split migration 경로의 최종 상태가 동일한지 dump 단위로 비교한다.
dump_db "$ORIGINAL_DB" "$TMP_DIR/original.sql"
dump_db "$SPLIT_DB" "$TMP_DIR/split.sql"

if diff -u "$TMP_DIR/original.sql" "$TMP_DIR/split.sql"; then
  echo "[ok] original migration and split migration produced identical final DB state"
else
  echo "[error] original migration and split migration final DB states differ" >&2
  echo "[error] debug files are in: $TMP_DIR" >&2
  trap - EXIT
  exit 1
fi
