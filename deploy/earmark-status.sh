#!/usr/bin/env bash
# What `/earmark` answers on Telegram: where to click, plus the handful of
# things that can rot without anyone noticing.
#
# The backup chain in particular is four links long — Windows on, WSL started,
# tailscaled up, push accepted — and every one of them fails quietly. A backup
# that stopped running two months ago looks exactly like one that ran last
# night, right up until you need it.
#
# Deliberately not `set -e`: a check that errors should print what went wrong
# and let the rest of the report continue. A status command that dies on its
# first bad probe tells you nothing about the other five.
set -uo pipefail

# shellcheck source=deploy/lib.sh
. "$(dirname "$(readlink -f "$0")")/lib.sh"

cd "$APP_DIR" 2>/dev/null || { echo "❌ $APP_DIR is missing — is Earmark deployed?"; exit 1; }

echo "🔗 $EARMARK_URL"
echo

problems=0
note_problem() { problems=$((problems + 1)); }

# --- containers -------------------------------------------------------------
for svc in postgres backend frontend; do
    cid="$("${COMPOSE[@]}" ps -q "$svc" 2>/dev/null)"
    if [ -z "$cid" ]; then
        echo "❌ $svc: not running"; note_problem; continue
    fi
    state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null)"
    # Not every service defines a healthcheck; treat a missing one as "no
    # opinion" rather than as a failure.
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' "$cid" 2>/dev/null)"
    if [ "$state" = "running" ] && [ "$health" != "unhealthy" ]; then
        echo "✅ $svc: $state${health:+ ($health)}"
    else
        echo "❌ $svc: $state${health:+ ($health)}"; note_problem
    fi
done

# --- does the app actually answer? -------------------------------------------
# Through nginx rather than straight at the backend, so this exercises the same
# proxy path a phone uses. A healthy backend behind a broken proxy is still a
# broken app.
if curl -fsS -m 10 "$EARMARK_LOCAL_URL/api/healthz" >/dev/null 2>&1; then
    echo "✅ api: responding through nginx"
else
    echo "❌ api: not responding on $EARMARK_LOCAL_URL/api/healthz"; note_problem
fi
echo

# --- last Plaid sync ---------------------------------------------------------
# Trimmed rather than stripped of all whitespace — the timestamp has a space in
# the middle of it, and deleting that turned "2026-08-14 19:32" into
# "2026-08-1419:32".
last_sync="$("${COMPOSE[@]}" exec -T postgres \
    psql -U budget -d budget -tAc "select coalesce(to_char(max(last_synced_at), 'YYYY-MM-DD HH24:MI'), 'never') from accounts" 2>/dev/null \
    | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
echo "🏦 last account sync: ${last_sync:-unknown}"

# --- backups -----------------------------------------------------------------
newest="$(ls -t "$BACKUP_DIR"/earmark-*.dump.gpg 2>/dev/null | head -1)"
if [ -n "$newest" ]; then
    age_h=$(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 3600 ))
    echo "💾 newest local backup: ${age_h}h old ($(basename "$newest"))"
else
    echo "❌ no backups in $BACKUP_DIR"; note_problem
fi

# A hard failure is reported before staleness and separately from it. Both
# would otherwise surface as the same 36h warning, which is precisely the
# conflation this is meant to avoid: "your desktop was off" and "the push is
# broken" need different reactions from you.
if [ -f "$ERROR_MARKER" ]; then
    echo "❌ last backup run FAILED:"
    sed 's/^/    /' "$ERROR_MARKER"
    note_problem
fi

if [ -f "$PUSH_MARKER" ]; then
    push_age_h=$(( ( $(date +%s) - $(stat -c %Y "$PUSH_MARKER") ) / 3600 ))
    if [ "$push_age_h" -gt "$STALE_HOURS" ]; then
        echo "⚠️  last push to connorpc: ${push_age_h}h ago — STALE (>${STALE_HOURS}h)"
        echo "    Is the Windows box on and WSL running?"
        note_problem
    else
        echo "📤 last push to connorpc: ${push_age_h}h ago"
    fi
else
    echo "⚠️  no successful push to connorpc yet"; note_problem
fi

# --- deployed revision -------------------------------------------------------
echo
echo "📦 deployed: $(git -C "$APP_DIR" log -1 --format='%h %s' 2>/dev/null || echo unknown)"

echo
if [ "$problems" -eq 0 ]; then
    echo "All good."
else
    echo "$problems problem(s) above."
fi
exit 0
