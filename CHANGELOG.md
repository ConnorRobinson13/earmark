# Changelog

All notable changes to Earmark are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Entries for 1.0.0 through 1.2.0 were
backfilled from the GitHub release notes.

## [Unreleased]

### Changed

- AI auto-sort runs only through OpenRouter, configured with `OPENROUTER_API_KEY`.
  The Anthropic fallback for fund suggestions is removed, and so is the
  `ANTHROPIC_API_KEY` setting. Fund suggestions now come from local embeddings
  alone, so nothing about a transaction leaves the machine for suggestions.

## [1.3.0] - 2026-10-25

### Added

- **Auto-sort review UI.** AI-suggested fund assignments for unassigned
  expenses are reviewed in the Inbox before anything is written. (#38)
- **Plaid login recovery.** Items that need re-authentication are repaired
  per item, through Plaid's Link update mode, instead of failing the whole
  sync. (#39)
- **Move an assigned transaction** to a different fund. (#36)
- **AI-assisted transaction auto-sorting** through OpenRouter. (#35)

### Changed

- The leftover `ronin` theme attribute is now `earmark`. The Ronin Systems
  branding was removed in 1.2.0, and this removes the last of it. (#40)

### Development

- GitHub Actions: backend, mcp, and frontend tests, a Docker build of all three
  images, lint, and CodeQL on every PR. (#41)
- ruff for backend and mcp, and ESLint for the frontend, both in CI. (#57)
- Dependabot for pip, npm, Docker, and Actions. Minor and patch bumps are
  grouped weekly; major bumps are held for manual review. (#58)
- Branch protection on `master`: the CI checks must pass and force-pushes are
  blocked. Secret scanning and push protection are on.

## [1.2.0] - 2026-10-12

### Added

- Move an assigned transaction to a different fund. (#36)
- AI-assisted transaction auto-sorting through OpenRouter. (#35)

### Removed

- The ninja logo from the frontend. (#34)

## [1.1.0] - 2026-08-21

Earmark deploys to production and works on a phone.

### Added

- **Production deployment** to a VPS, reachable only over Tailscale. Hermes is
  the source of truth, with encrypted backups pushed off-machine.
  `docker-compose.prod.yml` stands alone rather than overlaying the dev file.
- **A mobile layout** below 720px for every view. Forms open in a shared
  `Modal`, which is a bottom sheet on a phone.
- **Compact money on chart axes** where the exact figure does not fit. The
  exact amount stays in the markup beside it.

### Changed

- `deploy/earmark-deploy.sh` refuses to deploy when `alembic current` and
  `alembic heads` differ, leaving the previous version serving. Migrations are
  a deliberate human step.

### Fixed

- Nginx resolves the backend per request through Docker's DNS. Resolving at
  config load crash-looped the web tier whenever the backend was briefly
  absent.

### Tests

- Backend 254 passed; frontend 98 passed.

## [1.0.0] - 2026-08-06

First tagged release. This is a major version because the Planner and its
`/templates` endpoints are gone. Any client that calls them breaks.

### Breaking

- **The Planner is removed in full** (#31): the view, the `/templates`
  endpoints, the `MonthlyTemplate` model, and the `monthly_templates` table
  (migration `0017`). Assignments it had already applied are ordinary
  transactions and are untouched.
- **`GET /networth` no longer writes** (#21). Capturing history is now
  `POST /networth/snapshot`, which the Net Worth view calls on open (#27).
- **Pending settlements respect the month** (#29). A goal ended in an earlier
  month, or created after the month being viewed, no longer appears in the
  To-Move panel.
- **Bulk copy no longer resurrects archived funds** (#25).

### Added

- **Retirement projection lives in the backend** (#27). The web app and the MCP
  tool share one module and one endpoint. They previously disagreed on the same
  question.
- **A frontend resource module** (#16, #23) that owns reads, deduplicates
  in-flight requests, and aborts on unmount. The app-wide refresh tick is gone.
- **A frontend test suite**, with 98 tests rendering the real app against a
  stub adapter.

### Fixed

- **Settling and unsettling round-trip exactly** (#17). Settling `300.005` and
  undoing it used to leave a cent behind.
- **Plaid token exchange is one transaction** (#20). A failure between
  committing the Item and fetching its accounts used to strand an Item that
  could not be re-linked.
- **Writes no longer block on embeddings** (#19). Embedding runs off the write
  path, so a slow Ollama call no longer stalls a person waiting on a save.

### Internal

- The cash-flow projector is pure (#15). The test schema is built from the
  migrations, not `create_all` (#18). Plaid sync and net worth are services
  (#20, #21). One definition each of "active fund" (#25) and of the
  operational/goal split (#30).

### Upgrading

Run `alembic upgrade head`. Migration `0016` makes five timestamp columns
`NOT NULL`, and `0017` drops `monthly_templates`. Back up before `0017` if you
have a fixed-expense plan you want to keep. Its `downgrade` recreates the table
but not its contents.

[Unreleased]: https://github.com/ConnorRobinson13/earmark/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/ConnorRobinson13/earmark/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/ConnorRobinson13/earmark/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/ConnorRobinson13/earmark/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ConnorRobinson13/earmark/releases/tag/v1.0.0
