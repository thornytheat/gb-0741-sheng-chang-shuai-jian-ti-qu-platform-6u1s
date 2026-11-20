from fastapi import APIRouter, Depends

from app.modules.m1_intake.service import load
from app.modules.m6_reconcile.service import evaluate
from app.store import Store, get_store

router = APIRouter(prefix='/api/noise', tags=['噪声判废'])


@router.get('/{source_id}')
def get_noise(source_id: str, store: Store = Depends(get_store)):
    return evaluate(load(store, source_id))['noise']
