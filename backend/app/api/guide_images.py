from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.deps import CurrentAuth
from app.services.guide_image import GuideImageServiceDep

router = APIRouter(prefix="/guide-images", tags=["guide-images"])


@router.get("/{category}/{file_name}", response_class=FileResponse)
def get_guide_image(category: str, file_name: str, auth: CurrentAuth, service: GuideImageServiceDep) -> FileResponse:
    """DC-11. 파일이 바뀔 일이 드물어 브라우저에 잠시 둔다. 권한이 걸린 파일이라 공용 캐시에는 두지 않는다."""
    path = service.find_file(f"{category}/{file_name}", auth.user)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
