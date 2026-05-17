from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..services.suggest import suggest_fund

router = APIRouter(prefix="/suggest", tags=["suggest"])


@router.post("", response_model=schemas.SuggestResponse)
def suggest(body: schemas.SuggestRequest, db: Session = Depends(get_db)):
    fund_id, fund_name, source = suggest_fund(db, body.merchant, body.amount)
    return {"fund_id": fund_id, "fund_name": fund_name, "source": source}
