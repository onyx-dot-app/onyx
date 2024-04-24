from fastapi import APIRouter
from fastapi import Response

router = APIRouter(prefix="/api")


@router.get("/health")
def healthcheck() -> Response:
    return Response(status_code=200)
