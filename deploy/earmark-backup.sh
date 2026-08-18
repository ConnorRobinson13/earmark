#!/usr/bin/env bash
# Nightly backup: dump, encrypt, prune, push to connorpc.
#
# Encrypted because hermes is a rented VPS. The provider can snapshot that
# disk, so an unencrypted dump puts a complete financial history on hardware
# nobody here owns, in copies nobody here took.
#
# The passphrase must also exist somewhere other than this machine. Backups
# exist mainly for the case where hermes is the thing that died, and a
# passphrase whose only copy died with it protects the attacker's problem
# rather than yours. See deploy/README.md.
#
# On reachability: connorpc is a WSL instance on a desktop that is often off.
# That is expected, not a failure, and it is reported as such — a job that
# cries wolf every night you are away from your desk is a job whose output you
# will stop reading, which costs you the one real alert. Unreachable is quiet;
# reachable-but-failed is loud.
set -uo pipefail

APP_DIR="${EARMARK_DIR:-$HOME/apps/earmark}"
COMPOSE=(docker compose -f "$APP_DIR/docker-compose.prod.yml")
BACKUP_DIR="${EARMARK_BACKUP_DIR:-$HOME/backups/earmark}"
PASS_FILE="${EARMARK_PASS_FILE:-$HOME/.earmark-backup.pass}"
KEEP_DAYS="${EARMARK_KEEP_DAYS:-14}"

# connorpc — the WSL node. Pushes land as `earmarkbk`, an unprivileged account
# whose only job is receiving these files, so a compromised hermes gets a
# backup directory rather than a shell as connor.
PEER_HOST="${EARMARK_PEER_HOST:-100.79.146.80}"
PEER_USER="${EARMARK_PEER_USER:-earmarkbk}"
PEER_DIR="${EARMARK_PEER_DIR:-backups/earmark}"

PUSH_MARKER="$BACKUP_DIR/.last-push"
ERROR_MARKER="$BACKUP_DIR/.last-error"

TS="$(date +%Y%m%d-%H%M%S)"
NAME="earmark-$TS.dump.gpg"

fail() { echo "$1" >&2; printf '%s\n%s\n' "$(date -Is)" "$1" > "$ERROR_MARKER"; exit 1; }

# The dumps are encrypted, but there is no reason for them to be world-readable
# on the way in either.
umask 077

mkdir -p "$BACKUP_DIR"
[ -r "$PASS_FILE" ] || fail "passphrase file $PASS_FILE is missing or unreadable"

# --- dump + encrypt ---------------------------------------------------------
# Piped straight into gpg so the plaintext dump never lands on disk, not even
# briefly in a temp file that a failure could leave behind.
TMP="$BACKUP_DIR/.$NAME.partial"
trap 'rm -f "$TMP"' EXIT

if ! "${COMPOSE[@]}" exec -T postgres pg_dump -U budget -d budget -Fc 2>/dev/null \
    | gpg --batch --yes --quiet --passphrase-file "$PASS_FILE" \
          --symmetric --cipher-algo AES256 -o "$TMP"; then
    fail "dump/encrypt failed"
fi

# A dump of an empty or half-written database compresses to almost nothing.
# 1 KB is far below any real backup here and far above a zero-length file.
size=$(stat -c %s "$TMP")
[ "$size" -gt 1024 ] || fail "backup is only ${size}B — refusing to keep it"

mv "$TMP" "$BACKUP_DIR/$NAME"
trap - EXIT
echo "wrote $BACKUP_DIR/$NAME (${size}B)"

# --- prune ------------------------------------------------------------------
find "$BACKUP_DIR" -name 'earmark-*.dump.gpg' -mtime "+$KEEP_DAYS" -delete

# --- push -------------------------------------------------------------------
# Reachability is probed with a TCP connect to :22 rather than `tailscale ping`,
# because the ACL only opens port 22 in this direction — a ping would report
# "down" for a peer that is up and accepting the very connection we want.
if ! timeout 5 bash -c "</dev/tcp/$PEER_HOST/22" 2>/dev/null; then
    echo "connorpc unreachable — skipping push (expected when the desktop is off)"
    exit 0
fi

# Reachable from here on, so anything that fails now is a real fault.
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

if ! "${SSH[@]}" "$PEER_USER@$PEER_HOST" "mkdir -p '$PEER_DIR'" 2>/dev/null; then
    fail "connorpc is up but SSH as $PEER_USER failed — check the Tailscale ACL ssh block"
fi

# Written to a .partial and renamed, so an interrupted transfer can never be
# mistaken for a complete backup by whatever reads that directory later.
if ! "${SSH[@]}" "$PEER_USER@$PEER_HOST" \
        "cat > '$PEER_DIR/.$NAME.partial' && mv '$PEER_DIR/.$NAME.partial' '$PEER_DIR/$NAME'" \
        < "$BACKUP_DIR/$NAME"; then
    fail "push to connorpc failed"
fi

remote_size="$("${SSH[@]}" "$PEER_USER@$PEER_HOST" "stat -c %s '$PEER_DIR/$NAME'" 2>/dev/null)"
[ "$remote_size" = "$size" ] || fail "pushed size $remote_size != local $size"

"${SSH[@]}" "$PEER_USER@$PEER_HOST" \
    "find '$PEER_DIR' -name 'earmark-*.dump.gpg' -mtime +90 -delete" 2>/dev/null

date -Is > "$PUSH_MARKER"
rm -f "$ERROR_MARKER"
echo "pushed $NAME to $PEER_USER@connorpc:$PEER_DIR"
