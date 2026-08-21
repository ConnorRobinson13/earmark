#!/usr/bin/env bash
# Run this ON connorpc (the WSL box), with sudo. Sets up the receiving end of
# the backup push.
#
#   sudo ./deploy/connorpc-setup.sh
#
# Two things happen here, and the second is the one that matters:
#
# 1. An unprivileged `earmarkbk` account whose whole job is holding dump files.
#    hermes is the internet-facing machine, and it runs an LLM agent that reads
#    untrusted content — so the account it can reach on this desktop should own
#    nothing but a backup directory.
#
# 2. Tailscale SSH, instead of an sshd host key and an authorized_keys entry.
#    Authentication becomes tailnet identity governed by the ACL, which means
#    there is no long-lived private key sitting on the exposed box to steal,
#    and access can be revoked from the admin console rather than by editing
#    files on two machines.
#
# The ACL must also carry an `ssh` block allowing the `earmarkbk` user, or the
# connection is refused no matter what this script does. See deploy/README.md.
set -euo pipefail

BK_USER="${EARMARK_PEER_USER:-earmarkbk}"

[ "$(id -u)" -eq 0 ] || { echo "run me with sudo"; exit 1; }

if id "$BK_USER" >/dev/null 2>&1; then
    echo "user $BK_USER already exists"
else
    # --disabled-password: nothing should ever log in as this account with a
    # password. The only way in is Tailscale SSH, gated by the ACL.
    adduser --disabled-password --gecos "Earmark backups" "$BK_USER"
    echo "created $BK_USER"
fi

install -d -o "$BK_USER" -g "$BK_USER" -m 700 "/home/$BK_USER/backups/earmark"
echo "backup directory ready at /home/$BK_USER/backups/earmark"

if command -v tailscale >/dev/null 2>&1; then
    tailscale set --ssh
    echo "Tailscale SSH enabled"
else
    echo "WARNING: tailscale not found — install it, then run: sudo tailscale set --ssh"
fi

cat <<EOF

Done on this box. Remaining, in order:

  1. Apply the Tailscale ACL (admin console -> Access controls). Without its
     \`ssh\` block allowing $BK_USER, the push is refused.

  2. From hermes, prove the round trip:
       ssh hermes '~/apps/earmark/deploy/earmark-backup.sh'
     Expect it to write a dump AND report a push, not "connorpc unreachable".

  3. Verify what landed here actually restores:
       ./deploy/restore.sh --verify /home/$BK_USER/backups/earmark/earmark-*.dump.gpg

  4. Windows Task Scheduler, at logon, so this node is on the tailnet whenever
     the desktop is — not only when a terminal happens to be open:
       wsl.exe -d Ubuntu -u root -e sleep infinity
EOF
