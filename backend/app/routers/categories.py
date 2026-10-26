from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Category, Fund

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(func.lower(Category.name))).all()


@router.post("", response_model=schemas.CategoryOut, status_code=201)
def create_category(body: schemas.CategoryCreate, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "name is required")
    # Case-insensitive, so "Food" and "food" cannot both exist as separate choices.
    taken = db.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
    if taken:
        raise HTTPException(409, f"category '{taken.name}' already exists")
    c = Category(name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.delete("/{category_id}")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    c = db.get(Category, category_id)
    if not c:
        raise HTTPException(404)
    # Deleting a category that funds still point at would silently strip their
    # grouping, so refuse and say how many need moving first.
    in_use = db.scalar(
        select(func.count()).select_from(Fund).where(Fund.category_id == category_id)
    )
    if in_use:
        raise HTTPException(
            409, f"{in_use} fund(s) still use this category; move them first"
        )
    db.delete(c)
    db.commit()
    return {"deleted": True}
