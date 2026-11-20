from fastapi import APIRouter, Depends

from app.modules.m1_intake.service import load
from app.modules.m6_reconcile.service import evaluate
from app.store import Store, get_store

router = APIRouter(prefix='/api/calibration', tags=['量纲校准'])


@router.get('/{source_id}')
def get_calibration(source_id: str, store: Store = Depends(get_store)):
    # 与归档同一条评估链：缩短带只暴露采信段，保证曲线/拟合/勾稽对账到同一采信行
    return evaluate(load(store, source_id))['calibration']
