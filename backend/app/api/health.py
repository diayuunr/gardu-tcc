from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Health check dasar untuk memastikan server backend hidup."""
    return {"status": "ok"}
