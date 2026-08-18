# Deploying Earmark on hermes

Earmark runs always-on in Docker on `hermes`, reachable only over Tailscale at
**https://hermes.tailb39477.ts.net**. There is no public exposure and no
application login — the tailnet is the auth boundary, so the ACL is not
optional hardening, it *is* the access control.

hermes is the sole source of truth. Backups flow one way, to `connorpc`.

## Layout

| Path | What |
|---|---|
| `~/apps/earmark` | the checkout, deployed from `origin/master` |
| `~/apps/earmark/.env` | secrets, mode `0600`, never committed |
| `~/backups/earmark/` | encrypted dumps, 14 days |
| `~/.earmark-backup.pass` | GPG passphrase — **also keep a copy off this box** |

## First-time setup

### 1. Tailscale

Apply the ACL (admin console → Access controls). It must grant
`hermes → connorpc:22` and an `ssh` block allowing the `earmarkbk` user,
or backups cannot push. Enable HTTPS certificates under DNS.

### 2. On `connorpc` (the WSL box) — receives backups

```bash
sudo adduser --disabled-password --gecos "Earmark backups" earmarkbk
sudo -u earmarkbk mkdir -p /home/earmarkbk/backups/earmark
sudo tailscale set --ssh          # Tailscale SSH server; no keys to steal
```

Add a Windows Task Scheduler entry at logon so the node is on the tailnet
whenever the desktop is, not only when a terminal happens to be open:

```
wsl.exe -d Ubuntu -u root -e sleep infinity
```

### 3. On `hermes`

```bash
mkdir -p ~/apps && cd ~/apps
gh repo clone ConnorRobinson13/earmark
cd earmark

# Secrets. POSTGRES_PASSWORD is generated once, here — a fresh database is the
# only moment changing it is free.
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))" >> .env
$EDITOR .env        # add PLAID_CLIENT_ID / PLAID_SECRET / PLAID_ENV

# Backup passphrase
openssl rand -base64 48 > ~/.earmark-backup.pass && chmod 600 ~/.earmark-backup.pass
```

**Copy that passphrase into your password manager and onto `connorpc` now.**
Backups exist for the case where hermes is what died; a passphrase whose only
copy died with it is worthless.

### 4. Restore the data

```bash
docker compose -f docker-compose.prod.yml up -d postgres
docker compose -f docker-compose.prod.yml exec -T postgres \
    pg_restore -U budget -d budget --no-owner --no-privileges < earmark-cutover.dump
docker compose -f docker-compose.prod.yml up -d --build
```

Check the row counts match the source before going further.

### 5. Serve it

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8088
```

`serve`, never `funnel` — `funnel` publishes to the open internet, and this app
has no authentication of its own.

### 6. Backups

```bash
sudo cp deploy/systemd/earmark-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now earmark-backup.timer
sudo systemctl start earmark-backup.service   # prove it works now
```

Then verify a pushed dump actually restores, on `connorpc`:

```bash
./deploy/restore.sh --verify ~/backups/earmark/earmark-<ts>.dump.gpg
```

Until that has passed once, you have backups you have never tested.

## Day to day

| Command | Effect |
|---|---|
| `deploy/earmark-status.sh` | what `/earmark` reports on Telegram |
| `deploy/earmark-deploy.sh` | pull, rebuild, restart — refuses if a migration is pending |
| `deploy/earmark-backup.sh` | dump, encrypt, push (the timer runs this) |
| `deploy/restore.sh --verify F` | prove a backup is real, touching nothing |

## When a deploy refuses

`earmark-deploy.sh` stops rather than starting new code against an old schema:

```
❌ Migration pending — NOT deploying.
    database is at: 0017
    code expects:   0018
```

The old version keeps serving. Back up, apply the migration by hand, deploy
again — the exact commands are printed with the error. This is deliberate:
applying a schema change to real financial data is a decision to make while
looking at the migration, not something a chat message should trigger.
