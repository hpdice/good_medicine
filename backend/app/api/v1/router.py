from fastapi import APIRouter

from app.api.v1 import analysis, auth, drugs, medicine_box, users

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(drugs.router, prefix="/drugs", tags=["drugs"])
api_router.include_router(medicine_box.router, prefix="/medicine-box", tags=["medicine-box"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
