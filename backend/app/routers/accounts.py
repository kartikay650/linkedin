from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Burner
from app.schemas import BurnerOut

router = APIRouter(prefix="/burners", tags=["burners"])


@router.get("", response_model=list[BurnerOut])
def list_burners(db: Session = Depends(get_db)):
    return db.query(Burner).all()
