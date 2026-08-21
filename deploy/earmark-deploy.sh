#!/usr/bin/env bash
# Pull, rebuild, restart — with one gate in the middle.
#
# Nothing in this repo runs migrations automatically. That is fine while the
# schema is still, but the moment a PR adds `0018_*.py`, a plain
# `git pull && up -d --build` starts new code against an old database, and the
# symptom is a 500 that reads as "the app is down" rather than "you skipped a
# step". So: if the checkout wants a migration the database has not run, this
# script stops and says so, leaving the previous version serving.
#
# Running the migration is deliberately a human decision. It is the one action
# here that can destroy data, and it should be taken by someone looking at the
# specific migration, not by a chat message.
set -euo pipefail

# shellcheck source=deploy/lib.sh
. "$(dirname "$(readlink -f "$0")")/lib.sh"

# master in normal operation; overridable so a deployment can be validated from
# a branch before it is merged, which is the only way to test this script
# without merging first.
BRANCH="${EARMARK_BRANCH:-master}"

cd "$APP_DIR"

echo "▶ fetching origin/$BRANCH"
git fetch --quiet origin "$BRANCH"
before="$(git rev-parse HEAD)"
# --ff-only: a deployment should be a fast-forward to what is on the remote,
# never a merge commit invented on the server.
git merge --ff-only FETCH_HEAD
after="$(git rev-parse HEAD)"

if [ "$before" = "$after" ]; then
    echo "  already at $(git log -1 --format='%h %s')"
else
    echo "  $(git log --oneline "$before..$after" | wc -l) new commit(s):"
    git log --oneline "$before..$after" | sed 's/^/    /'
fi

echo "▶ building"
"${COMPOSE[@]}" build

# --- the gate ---------------------------------------------------------------
# `alembic current` reports what the database has applied; `alembic heads` what
# the checkout expects. Run against the freshly built image so the answer
# reflects the code about to be deployed, not the code currently running.
echo "▶ checking migrations"
db_rev="$("${COMPOSE[@]}" run --rm -T backend alembic current 2>/dev/null | grep -oE '^[0-9a-z_]+' | tail -1)"
mapfile -t code_revs < <("${COMPOSE[@]}" run --rm -T backend alembic heads 2>/dev/null | grep -oE '^[0-9a-z_]+')

if [ -z "$db_rev" ] || [ "${#code_revs[@]}" -eq 0 ]; then
    echo "❌ could not read migration state (db='$db_rev' heads='${code_revs[*]:-}')."
    echo "   Not deploying. The previous version is still running."
    exit 1
fi

# More than one head means the migration tree has branched — two migrations
# claiming the same parent. Picking one and comparing against it would report
# "up to date" while half the schema change sits unapplied, so refuse instead.
if [ "${#code_revs[@]}" -gt 1 ]; then
    echo "❌ Multiple migration heads: ${code_revs[*]}"
    echo "   The tree has branched and needs a merge revision. Not deploying."
    exit 2
fi

code_rev="${code_revs[0]}"
if [ "$db_rev" != "$code_rev" ]; then
    cat <<EOF
❌ Migration pending — NOT deploying.

    database is at: $db_rev
    code expects:   $code_rev

The previous version is still running and serving normally. To go ahead,
back up first and then apply it by hand:

    $APP_DIR/deploy/earmark-backup.sh
    docker compose -f $APP_DIR/docker-compose.prod.yml run --rm backend alembic upgrade head
    $APP_DIR/deploy/earmark-deploy.sh
EOF
    exit 2
fi
echo "  schema $db_rev — up to date"

echo "▶ restarting"
"${COMPOSE[@]}" up -d --remove-orphans

echo "▶ waiting for health"
for _ in $(seq 1 30); do
    if curl -fsS -m 5 "$EARMARK_LOCAL_URL/api/healthz" >/dev/null 2>&1; then
        echo "✅ deployed $(git log -1 --format='%h %s')"
        exit 0
    fi
    sleep 2
done

echo "⚠️  deployed, but the API did not answer within 60s. Check:"
echo "    docker compose -f $APP_DIR/docker-compose.prod.yml logs --tail=50 backend"
exit 1
