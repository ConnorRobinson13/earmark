"""Admin actions — dev/local-only conveniences."""
import subprocess
import sys

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset-to-seed")
def reset_to_seed(keep_accounts: bool = True):
    """Wipe budget data and re-run the seed script.

    keep_accounts (default True): preserves Plaid items + Account rows so live
    bank linkage stays intact. Wipes funds, transactions, inbox,
    goal_settlements only. Pass ?keep_accounts=false to nuke everything.
    """
    args = [sys.executable, "scripts/seed.py"]
    if keep_accounts:
        args.append("--keep-accounts")
    proc = subprocess.run(
        args, cwd="/app", capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise HTTPException(500, f"seed failed: {proc.stderr or proc.stdout}")
    return {"ok": True, "output": proc.stdout.strip().splitlines()[-20:]}
