"""Admin actions — dev/local-only conveniences."""
import subprocess
import sys

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset-to-seed")
def reset_to_seed():
    """Wipe all data and re-run the seed script. Local single-user only."""
    proc = subprocess.run(
        [sys.executable, "scripts/seed.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise HTTPException(500, f"seed failed: {proc.stderr or proc.stdout}")
    return {"ok": True, "output": proc.stdout.strip().splitlines()[-20:]}
