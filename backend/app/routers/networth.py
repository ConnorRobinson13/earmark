"""Net worth: current breakdown across all accounts + monthly history.

The arithmetic lives in `app.services.networth`; this layer only serializes it
and owns the commit for the one endpoint that writes.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import NetWorthSnapshot
from ..services.networth import (
    NetWorth,
    capture_snapshot,
    compute_net_worth,
    snapshot_history,
)

router = APIRouter(prefix="/networth", tags=["networth"])


def _serialize(nw: NetWorth) -> dict:
    # Money crosses the wire as strings so no client rounds a Decimal into a float.
    return {
        "total": str(nw.total),
        "liquid": str(nw.liquid),
        "investment": str(nw.investment),
        "emergency_fund": str(nw.emergency_fund),
        "credit_debt": str(nw.credit_debt),
        "loan_debt": str(nw.loan_debt),
        "by_type": {k: str(v) for k, v in nw.by_type.items()},
        "accounts": [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type.value,
                "balance": str(a.current_balance),
                "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
            }
            for a in nw.accounts
        ],
    }


def _serialize_snapshot(s: NetWorthSnapshot) -> dict:
    return {
        "month": s.month.isoformat(),
        "total": str(s.total),
        "liquid": str(s.liquid),
        "investment": str(s.investment),
        "emergency_fund": str(s.emergency_fund),
        "credit_debt": str(s.credit_debt),
        "loan_debt": str(s.loan_debt),
    }


@router.get("")
def networth(db: Session = Depends(get_db)):
    """Current breakdown by account type.

    Returns:
      liquid:     checking + savings  (cash you can spend)
      investment: IRAs / brokerage    (long-term)
      credit:     positive number     (debt — pulled out of total)
      loan_debt:  positive number     (still owed on debt funds)
      total:      liquid + investment + emergency − credit − loan
      accounts:   per-account rows
    """
    return _serialize(compute_net_worth(db))


@router.post("/snapshot", status_code=201)
def snapshot(db: Session = Depends(get_db)):
    """Record this month's net worth for the trend chart.

    Separate from the GET on purpose: reading net worth used to upsert a
    snapshot as a side effect, which meant every page load wrote to the
    database. Capturing history is now something a caller asks for.
    """
    snap = capture_snapshot(db)
    db.commit()
    return _serialize_snapshot(snap)


@router.get("/history")
def networth_history(db: Session = Depends(get_db)):
    """Ordered monthly net-worth snapshots for the trend chart."""
    return [_serialize_snapshot(s) for s in snapshot_history(db)]
