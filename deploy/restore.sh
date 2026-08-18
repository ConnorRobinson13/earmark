#!/usr/bin/env bash
# Break glass. Restores an encrypted backup into a database.
#
# This is not part of any normal workflow, and it is not a way to "run Earmark
# locally". hermes is the only source of truth; a second writable copy of this
# data diverges silently and nothing in this app reconciles it. If you are
# restoring, either hermes is gone or you are verifying that a backup is real.
#
# Verifying is the good reason, and you should do it: a backup nobody has ever
# restored is a hypothesis. Use --verify, which restores into a throwaway
# container and prints row counts, touching nothing that matters.
#
# Usage:
#   ./restore.sh --verify  earmark-20260818-060000.dump.gpg
#   ./restore.sh --into-db earmark-20260818-060000.dump.gpg   # real restore
set -euo pipefail

MODE="${1:-}"
FILE="${2:-}"
PASS_FILE="${EARMARK_PASS_FILE:-$HOME/.earmark-backup.pass}"
APP_DIR="${EARMARK_DIR:-$HOME/apps/earmark}"

TABLES="funds accounts transactions monthly_meta goal_settlements plaid_inbox payday_schedule networth_snapshots plaid_items alembic_version"

usage() { sed -n '2,17p' "$0" | sed 's/^# \?//'; exit 1; }
[ -n "$FILE" ] && [ -r "$FILE" ] || usage
[ -r "$PASS_FILE" ] || { echo "passphrase file $PASS_FILE missing"; exit 1; }

counts_sql() {
    local first=1
    for t in $TABLES; do
        [ $first -eq 1 ] && first=0 || printf ' union all '
        printf "select '%s', count(*) from %s" "$t" "$t"
    done
    printf ' order by 1;'
}

case "$MODE" in
--verify)
    # A disposable container on a random high port, removed on exit whatever
    # happens. Nothing here touches the deployed stack.
    CID="earmark-restore-check-$$"
    trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT
    echo "▶ starting throwaway postgres"
    docker run -d --name "$CID" \
        -e POSTGRES_USER=budget -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=budget \
        pgvector/pgvector:pg16 >/dev/null
    for _ in $(seq 1 30); do
        docker exec "$CID" pg_isready -U budget >/dev/null 2>&1 && break
        sleep 2
    done
    docker exec "$CID" psql -U budget -d budget -c 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null

    echo "▶ decrypting and restoring"
    gpg --batch --quiet --passphrase-file "$PASS_FILE" --decrypt "$FILE" \
        | docker exec -i "$CID" pg_restore -U budget -d budget --no-owner --no-privileges

    echo "▶ row counts"
    docker exec "$CID" psql -U budget -d budget -tAc "$(counts_sql)"
    echo "✅ backup restores cleanly. Compare the counts above against /earmark."
    ;;

--into-db)
    # The real thing. Refuses to run silently because it replaces live data.
    echo "This DROPS and recreates the deployed database at $APP_DIR."
    read -r -p "Type the word 'restore' to continue: " confirm
    [ "$confirm" = "restore" ] || { echo "aborted"; exit 1; }

    COMPOSE=(docker compose -f "$APP_DIR/docker-compose.prod.yml")
    echo "▶ stopping writers"
    "${COMPOSE[@]}" stop backend frontend

    echo "▶ recreating database"
    "${COMPOSE[@]}" exec -T postgres psql -U budget -d postgres \
        -c 'DROP DATABASE IF EXISTS budget WITH (FORCE);' -c 'CREATE DATABASE budget OWNER budget;'
    "${COMPOSE[@]}" exec -T postgres psql -U budget -d budget \
        -c 'CREATE EXTENSION IF NOT EXISTS vector;'

    echo "▶ restoring"
    gpg --batch --quiet --passphrase-file "$PASS_FILE" --decrypt "$FILE" \
        | "${COMPOSE[@]}" exec -T postgres pg_restore -U budget -d budget --no-owner --no-privileges

    echo "▶ row counts"
    "${COMPOSE[@]}" exec -T postgres psql -U budget -d budget -tAc "$(counts_sql)"

    "${COMPOSE[@]}" start backend frontend
    echo "✅ restored."
    ;;

*)
    usage
    ;;
esac
