"""The retirement projection's HTTP contract — the one both clients read.

Deliberately its own router rather than a third net-worth endpoint: net worth is
a statement of where the money is, and this is a guess about where it goes. The
only thing they share is the figure the guess starts from.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.networth import compute_net_worth
from ..services.retirement import ProjectionParams, RetirementProjection, project

router = APIRouter(prefix="/retirement", tags=["retirement"])


@router.get("/projection", response_model=RetirementProjection)
def projection(
    params: Annotated[ProjectionParams, Query()],
    db: Session = Depends(get_db),
):
    """Project the investment balance forward to retirement.

    Every assumption is a query parameter; the one thing the caller does not
    supply is where the money starts, which is the current investment-account
    total. Deriving it here rather than accepting it is what makes two clients
    asking the same question get the same answer — neither can pass a stale or
    differently-defined balance in.

    Look up, then project: the session stops at this line, and the recurrence
    behind it never sees one.
    """
    return project(params, compute_net_worth(db).investment)
