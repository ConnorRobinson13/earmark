#!/usr/bin/env bash
# Break glass. Restores an encrypted backup into a database.
#
# This is not part of any normal workflow, and it is not a way to "run Earmark
# locally". hermes is the only source of truth; a second writable copy of this
# data diverges silently and nothing in this app reconciles it. If you are
# restoring, either hermes is gone or you are verifying that a backup is real.
#
# Verifying is the good reason, and you should do it: a backup nobody has ever
# restored is a hypothesis.
set -euo pipefail

# shellcheck source=deploy/lib.sh
. "$(dirname "$(readlink -f "$0")")/lib.sh"

MODE="${1:-}"
FILE="${2:-}"

usage() {
    cat <<'EOF'
Restore an encrypted Earmark backup.

  restore.sh --verify  <file.dump.gpg>   restore into a throwaway container and
                                         print row counts. Touches nothing.

  restore.sh --into-db <file.dump.gpg>   replace the deployed database. Asks for
                                         confirmation. Destroys what is there.

The passphrase is read from $EARMARK_PASS_FILE (default ~/.earmark-backup.pass).
EOF
    exit 1
}

[ -n "$FILE" ] && [ -r "$FILE" ] || usage
[ -r "$PASS_FILE" ] || { echo "passphrase file $PASS_FILE missing"; exit 1; }

# Counts every table the database actually has, rather than a list maintained
# by hand here. A hand-kept list stops covering a new model silently, and the
# place that goes wrong is backup verification — where a missing table looks
# exactly like a table that was always empty.
counts_sql_for() {
    local runner=("$@")
    "${runner[@]}" psql -U budget -d budget -tAc "
        select string_agg(
            format('select %L, count(*) from %I', tablename, tablename),
            ' union all ' order by tablename)
        from pg_tables where schemaname = 'public';"
}

case "$MODE" in
--verify)
    # A disposable container, removed on exit whatever happens. Nothing here
    # touches the deployed stack.
    CID="earmark-restore-check-$$"
    trap 'docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT
    echo "▶ starting throwaway postgres"
    docker run -d --name "$CID" \
        -e POSTGRES_USER=budget -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=budget \
        pgvector/pgvector:pg16 >/dev/null
    until docker exec "$CID" pg_isready -U budget >/dev/null 2>&1; do sleep 2; done
    docker exec "$CID" psql -U budget -d budget -c 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null

    echo "▶ decrypting and restoring"
    gpg --batch --quiet --passphrase-file "$PASS_FILE" --decrypt "$FILE" \
        | docker exec -i "$CID" pg_restore -U budget -d budget --no-owner --no-privileges

    echo "▶ row counts"
    sql="$(counts_sql_for docker exec "$CID")"
    docker exec "$CID" psql -U budget -d budget -tAc "$sql"
    echo "✅ backup restores cleanly. Compare the counts above against /earmark."
    ;;

--into-db)
    # The real thing. Refuses to run silently because it replaces live data.
    echo "This DROPS and recreates the deployed database at $APP_DIR."
    read -r -p "Type the word 'restore' to continue: " confirm
    [ "$confirm" = "restore" ] || { echo "aborted"; exit 1; }

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
    sql="$(counts_sql_for "${COMPOSE[@]}" exec -T postgres)"
    "${COMPOSE[@]}" exec -T postgres psql -U budget -d budget -tAc "$sql"

    "${COMPOSE[@]}" start backend frontend
    echo "✅ restored."
    ;;

*)
    usage
    ;;
esac
