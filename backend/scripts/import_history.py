"""Import historical EveryDollar transactions for trend analysis only.

This brings in old EveryDollar monthly exports as READ-ONLY history that lights
up the month-scoped spend/category trend views WITHOUT touching any current
state. It does this by routing every imported row into a set of hidden,
archived "[History] <group>" funds:

  * archived_at is set  -> excluded from the dashboard, the funds list, and the
    cash-flow projection (all of which filter archived_at IS NULL).
  * effective_to_month is set in the past -> belt-and-suspenders exclusion.
  * kind = operational + category = the EveryDollar group -> they DO show up in
    spend_by_category_in_month / gross_spent_in_month, which are month-scoped,
    so they only ever surface when you view their historical month.

Safety properties (verified against services/balances.py):
  * Account balances / net worth: untouched (those read Account.current_balance
    and never sum transactions).
  * Unassigned: untouched (driven by MonthlyMeta planned income minus
    `assignment`-type rows; we import zero of either).
  * Savings goals "saved": untouched (reads goal_settlements; we add none).
  * "Total in funds" headline (all_funds_total): kept correct by a one-line
    guard added in balances.py that excludes archived funds (your only real
    archived fund nets 0, so its number is unchanged).

Row mapping (EveryDollar `Type` is ignored; sign of Amount drives type):
  * Group == "Income"        -> untagged income (fund_id NULL, type=income).
  * Amount <  0              -> expense on the group's [History] fund.
  * Amount >= 0 (non-income) -> income on the group's [History] fund
                                (reimbursements: roommate Zelle/Venmo, refunds).

Dry-run by default. Pass --commit to write. Idempotent guard: refuses to commit
if any "[History] " fund already exists.

Run inside the backend container:
  docker compose exec -w /app backend python -m scripts.import_history          # dry-run
  docker compose exec -w /app backend python -m scripts.import_history --commit  # write
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.db import new_session  # noqa: E402
from app.models import Fund, FundKind, Transaction, TxType  # noqa: E402

DATA_DIR = Path(__file__).parent / "history_csvs"
MONTHS = [
    "06-2025", "07-2025", "08-2025", "09-2025", "10-2025",
    "11-2025", "12-2025", "01-2026", "02-2026", "03-2026",
]
INCOME_GROUP = "Income"
HIST_PREFIX = "[History] "
# Anchors that keep these funds out of every "current" view.
HIST_CREATED_AT = datetime(2025, 6, 1)
HIST_EFFECTIVE_TO = date(2026, 3, 1)
HIST_SORT_BASE = 9000


def parse_rows() -> list[dict]:
    rows: list[dict] = []
    for m in MONTHS:
        p = DATA_DIR / f"{m}-EveryDollar-Transactions.csv"
        if not p.exists() or p.stat().st_size == 0:
            continue
        with p.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                amt = Decimal(str(r["Amount"] or "0")).quantize(Decimal("0.01"))
                mm, dd, yy = r["Date"].split("/")
                rows.append(
                    {
                        "group": r["Group"].strip(),
                        "item": r["Item"].strip(),
                        "date": date(int(yy), int(mm), int(dd)),
                        "merchant": (r["Merchant"] or "").strip(),
                        "amount": amt,
                        "note": (r["Note"] or "").strip(),
                        "src": m,
                    }
                )
    return rows


def build_plan(rows: list[dict]):
    """Return (groups, per_month) where groups maps group->stats and per_month
    maps (YYYY-MM)->{group: net_spend}. Income is bucketed under '<Income>'."""
    groups: dict[str, dict] = defaultdict(lambda: {"expense": 0, "income": 0, "net": Decimal("0")})
    per_month: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    income_total = Decimal("0")
    for r in rows:
        ym = f"{r['date'].year:04d}-{r['date'].month:02d}"
        if r["group"] == INCOME_GROUP:
            income_total += r["amount"]
            per_month[ym]["<Income>"] += r["amount"]
            continue
        g = groups[r["group"]]
        if r["amount"] < 0:
            g["expense"] += 1
        else:
            g["income"] += 1
        g["net"] += r["amount"]
        per_month[ym][r["group"]] += -r["amount"]  # positive = net spent
    return groups, per_month, income_total


def print_report(rows, groups, per_month, income_total):
    print("=" * 70)
    print(f"DRY RUN — parsed {len(rows)} rows from {DATA_DIR}")
    print(f"Date range: {min(r['date'] for r in rows)} -> {max(r['date'] for r in rows)}")
    print("=" * 70)
    print("\nHidden funds to create (kind=operational, archived, category=group):")
    for grp in sorted(groups):
        g = groups[grp]
        print(
            f"  {HIST_PREFIX + grp:26}  category={grp:16}  "
            f"expense_rows={g['expense']:4}  income_rows={g['income']:3}  "
            f"net_balance={g['net']:>10.2f}"
        )
    print(f"\nIncome (untagged, fund_id NULL): rows summing to {income_total:.2f}")
    print("\nNet spend by month x category (positive = spent):")
    cats = sorted({c for mm in per_month.values() for c in mm if c != "<Income>"})
    header = "  month    " + "".join(f"{c[:10]:>11}" for c in cats) + f"{'INCOME':>11}"
    print(header)
    for ym in sorted(per_month):
        line = f"  {ym}  "
        for c in cats:
            v = per_month[ym].get(c, Decimal("0"))
            line += f"{v:>11.2f}"
        line += f"{per_month[ym].get('<Income>', Decimal('0')):>11.2f}"
        print(line)
    print("\nNo database changes were made (dry run). Re-run with --commit to write.")


def commit(rows, groups):
    db = new_session()
    try:
        existing = db.scalars(
            select(Fund).where(Fund.name.like(HIST_PREFIX + "%"))
        ).all()
        if existing:
            print(
                f"ABORT: {len(existing)} '[History] ' fund(s) already exist. "
                "History looks already imported. Restore from backup and drop them "
                "first if you want to re-run."
            )
            return 1

        fund_by_group: dict[str, Fund] = {}
        for i, grp in enumerate(sorted(groups)):
            f = Fund(
                name=HIST_PREFIX + grp,
                kind=FundKind.operational,
                category=grp,
                archived_at=HIST_CREATED_AT,  # archived from the start -> hidden
                effective_to_month=HIST_EFFECTIVE_TO,
                created_at=HIST_CREATED_AT,
                sort_order=HIST_SORT_BASE + i,
                due_day=1,
            )
            db.add(f)
            fund_by_group[grp] = f
        db.flush()  # assign ids

        n_exp = n_inc = n_untagged = 0
        for r in rows:
            note = " · ".join(p for p in [r["item"], r["note"]] if p)
            note = (note + " " if note else "") + "[ed-import]"
            merchant = r["merchant"] or r["item"]
            if r["group"] == INCOME_GROUP:
                db.add(Transaction(
                    fund_id=None, type=TxType.income, amount=r["amount"],
                    date=r["date"], merchant=merchant, notes=note,
                ))
                n_untagged += 1
            else:
                is_exp = r["amount"] < 0
                db.add(Transaction(
                    fund_id=fund_by_group[r["group"]].id,
                    type=TxType.expense if is_exp else TxType.income,
                    amount=r["amount"], date=r["date"],
                    merchant=merchant, notes=note,
                ))
                if is_exp:
                    n_exp += 1
                else:
                    n_inc += 1
        db.commit()
        print(
            f"COMMITTED: {len(groups)} hidden funds, "
            f"{n_exp} expense + {n_inc} reimbursement (income) fund rows, "
            f"{n_untagged} untagged income rows."
        )
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    do_commit = "--commit" in sys.argv[1:]
    rows = parse_rows()
    if not rows:
        print(f"No rows found in {DATA_DIR}")
        return 1
    groups, per_month, income_total = build_plan(rows)
    if do_commit:
        return commit(rows, groups)
    print_report(rows, groups, per_month, income_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
