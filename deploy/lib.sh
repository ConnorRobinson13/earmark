# shellcheck shell=bash
# shellcheck disable=SC2034  # every variable here is consumed by a sourcing script
#
# Shared configuration for the deploy scripts. Sourced, never executed.
#
# Everything here is overridable from the environment, and the site-specific
# values live in the deployment's own `.env` rather than in this file. That
# split matters because this repo is public and the app has no login of its
# own — the tailnet is the entire access control, so the hostname and the peer
# address are part of the security posture, not just configuration. The
# defaults below are therefore generic; hermes gets the real ones from `.env`.
#
# It also puts the published port in one place. It was previously repeated in
# the compose file, two scripts and the README, which made changing it a
# five-file edit and an easy thing to get half-right.

EARMARK_DIR="${EARMARK_DIR:-$HOME/apps/earmark}"
APP_DIR="$EARMARK_DIR"

# Read EARMARK_* overrides out of the deployment's .env. Only those keys, so
# sourcing this never drags POSTGRES_PASSWORD and the Plaid secrets into the
# environment of a script that has no business holding them.
# Parsed rather than sourced or eval'd: `.env` is a data file, and running it as
# shell would let a stray `$(...)` in a config value execute as this user.
if [ -r "$APP_DIR/.env" ]; then
    while IFS='=' read -r _key _val; do
        _val="${_val%\"}"; _val="${_val#\"}"
        export "$_key=$_val"
    done < <(grep -E '^EARMARK_[A-Z_]+=' "$APP_DIR/.env" || true)
    unset _key _val
fi

COMPOSE=(docker compose -f "$APP_DIR/docker-compose.prod.yml")

# The loopback port nginx publishes on, and the URL `tailscale serve` fronts it
# with. The URL is only ever displayed; nothing dials it.
EARMARK_HTTP_PORT="${EARMARK_HTTP_PORT:-8088}"
EARMARK_LOCAL_URL="http://127.0.0.1:$EARMARK_HTTP_PORT"
EARMARK_URL="${EARMARK_URL:-http://127.0.0.1:$EARMARK_HTTP_PORT}"

BACKUP_DIR="${EARMARK_BACKUP_DIR:-$HOME/backups/earmark}"
PASS_FILE="${EARMARK_PASS_FILE:-$HOME/.earmark-backup.pass}"
KEEP_DAYS="${EARMARK_KEEP_DAYS:-14}"
STALE_HOURS="${EARMARK_STALE_HOURS:-36}"

PUSH_MARKER="$BACKUP_DIR/.last-push"
ERROR_MARKER="$BACKUP_DIR/.last-error"

# The machine that receives pushed backups, and the unprivileged account the
# push lands as. No default host: a script that silently falls back to some
# address baked into a public repo is worse than one that says it is not
# configured.
PEER_HOST="${EARMARK_PEER_HOST:-}"
PEER_USER="${EARMARK_PEER_USER:-earmarkbk}"
PEER_DIR="${EARMARK_PEER_DIR:-backups/earmark}"
