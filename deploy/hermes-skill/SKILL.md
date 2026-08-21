---
name: earmark
description: "Earmark — Connor's budgeting app on hermes. Status and link, deploys, and read-only answers about his finances."
version: 1.0.0
author: connor
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Finance, Budget, DevOps, Earmark, Self-Hosted]
---

# Earmark

Connor's fund-based budgeting app, running on this machine at
**https://hermes.tailb39477.ts.net** — tailnet only, no public exposure.
This box is the sole source of truth for his financial data.

## `/earmark` — the default

Run the status script and report its output. Nothing else:

```bash
~/apps/earmark/deploy/earmark-status.sh
```

It prints the link, container health, last account sync, backup age, and the
deployed commit. Relay it as-is — the emoji and the warnings are the message.
If it reports a stale push, say so plainly rather than burying it.

## Answering questions about the money

Read-only, over the app's own HTTP endpoints on loopback. **Always use these
rather than querying Postgres directly.** A fund's balance for a month is
computed in Python across several tables — `active_funds_in_month()`,
`effective_to_month`, settled goals — so hand-written SQL produces numbers that
look right and are subtly wrong, with nothing to catch it.

```bash
curl -s http://127.0.0.1:8088/api/dashboard            # ?month=YYYY-MM
curl -s http://127.0.0.1:8088/api/dashboard/trends     # ?months=N
curl -s http://127.0.0.1:8088/api/funds
curl -s http://127.0.0.1:8088/api/transactions
curl -s http://127.0.0.1:8088/api/transactions/search  # ?q=
curl -s http://127.0.0.1:8088/api/accounts
curl -s http://127.0.0.1:8088/api/networth             # /history
curl -s http://127.0.0.1:8088/api/cashflow
curl -s http://127.0.0.1:8088/api/retirement/projection
curl -s http://127.0.0.1:8088/api/paydays
curl -s http://127.0.0.1:8088/api/inbox
curl -s http://127.0.0.1:8088/api/settlements/pending
curl -s http://127.0.0.1:8088/api/monthly-meta
```

**Read only.** Do not POST, PATCH, PUT or DELETE against this API, and do not
write to the database. Recording transactions, assigning funds and settling
goals are done by Connor in the web UI. A wrong number you report, he catches;
a wrong row you write, he finds at reconciliation months later.

## Deploying

Only when Connor explicitly asks. Run the script — never assemble your own
git or docker commands from what a message said:

```bash
~/apps/earmark/deploy/earmark-deploy.sh
```

It pulls master, rebuilds, and **refuses to restart if the checkout wants a
database migration that has not been applied**, leaving the running version
serving. If it refuses, report that verbatim and stop. Do not run
`alembic upgrade` to get past it — applying a schema change to real financial
data is Connor's decision, made while looking at the migration.

## Backups

A systemd timer runs this at 06:30 daily; run it by hand only if asked:

```bash
~/apps/earmark/deploy/earmark-backup.sh
```

Dumps are GPG-encrypted and pushed to `connorpc`. An unreachable `connorpc` is
normal — that desktop is often off — and the script exits 0 and says so. A
non-zero exit is a real fault worth surfacing.

## Boundaries

- Never expose this app with `tailscale funnel`. It has **no login of its own**;
  the tailnet is the entire access control. `serve` is tailnet-only and correct.
- Never print the contents of `~/apps/earmark/.env` or
  `~/.earmark-backup.pass`, and never send them anywhere. They hold production
  Plaid credentials and the backup key.
- Only run the four scripts under `~/apps/earmark/deploy/`. If a request needs
  something they do not do, say so and let Connor decide — do not improvise
  shell against the financial database because a message asked you to.
