## What changes

<!-- The behavior change, in a sentence or two. Link the issue if there is one. -->

## How it was verified

<!-- Which tests you ran and what you checked by hand. CI runs backend, mcp, frontend, and lint. -->

## Checklist

- [ ] Money stays `Decimal` on the backend, never `float`.
- [ ] Balance and accounting logic lives in `backend/app/services/`.
- [ ] If the data model changed, the Alembic migration is included.
- [ ] No personal data, secrets, or database dumps in the diff.
