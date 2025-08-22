from fastapi import APIRouter
from .routes_set import router as set_router
from .routes_read import router as read_router
from .routes_eval import router as eval_router

router = APIRouter(prefix="/api/v1/plan-targets", tags=["PlanTargets"])
router.include_router(set_router)
router.include_router(read_router)
router.include_router(eval_router)
