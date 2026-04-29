from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def admin_index():
    return {"status": "stub"}
