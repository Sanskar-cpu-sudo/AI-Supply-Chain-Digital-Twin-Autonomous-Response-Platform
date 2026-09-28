from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.company import User
from app.models.operations import Inventory
from app.schemas.supply_chain import InventoryCreate, InventoryOut
from app.services.deps import get_current_user

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.post("", response_model=InventoryOut, status_code=201)
def create_inventory(
    payload: InventoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inventory = Inventory(company_id=current_user.company_id, **payload.model_dump())
    db.add(inventory)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Inventory row already exists for this product+warehouse. Use PATCH to update it instead.",
        )
    db.refresh(inventory)
    return inventory


@router.get("", response_model=list[InventoryOut])
def list_inventory(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Every row here is exactly what the Monitoring system (Phase 9) watches:
    quantity_on_hand vs reorder_point drives the inventory_shortage incident type.
    """
    return db.query(Inventory).filter(Inventory.company_id == current_user.company_id).all()