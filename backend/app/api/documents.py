from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import AdminAuth, CurrentAuth
from app.schemas.common import ItemList, Page
from app.schemas.document import (
    Document,
    DocumentCreateRequest,
    DocumentListQuery,
    DocumentUpdateRequest,
    DocumentVersion,
    DocumentVersionUpdateRequest,
    TransferPolicy,
    ViewScope,
)
from app.services.document import DocumentServiceDep

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=Page[Document])
def list_documents(query: Annotated[DocumentListQuery, Query()], auth: CurrentAuth, service: DocumentServiceDep) -> Page[Document]:
    return service.list_documents(query, auth.user)


@router.post("", response_model=Document, status_code=status.HTTP_201_CREATED)
def create_document(body: DocumentCreateRequest, _: AdminAuth, service: DocumentServiceDep) -> Document:
    return service.create(body)


@router.get("/{document_id}", response_model=Document)
def get_document(document_id: int, auth: CurrentAuth, service: DocumentServiceDep) -> Document:
    return service.get_document(document_id, auth.user)


@router.patch("/{document_id}", response_model=Document)
def update_document(document_id: int, body: DocumentUpdateRequest, auth: AdminAuth, service: DocumentServiceDep) -> Document:
    return service.update(document_id, body, auth.user)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, auth: AdminAuth, service: DocumentServiceDep) -> Response:
    service.delete(document_id, auth.user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}/versions", response_model=ItemList[DocumentVersion])
def list_versions(document_id: int, _: AdminAuth, service: DocumentServiceDep) -> ItemList[DocumentVersion]:
    return service.list_versions(document_id)


@router.post("/{document_id}/versions", response_model=DocumentVersion, status_code=status.HTTP_202_ACCEPTED)
def upload_version(
    document_id: int,
    auth: AdminAuth,
    service: DocumentServiceDep,
    file: Annotated[UploadFile, File()],
    version: Annotated[str, Form(min_length=1, max_length=20)],
    view_scope: Annotated[ViewScope, Form(alias="viewScope")] = "ADMIN",
    transfer_policy: Annotated[TransferPolicy, Form(alias="transferPolicy")] = "BLOCKED",
) -> DocumentVersion:
    """적재는 백그라운드로 한다. 상태는 DC-08 로 확인한다."""
    return service.upload_version(document_id, file.file, file.filename, version.strip(), view_scope, transfer_policy, auth.user)


@router.get("/{document_id}/versions/{version_id}", response_model=DocumentVersion)
def get_version(document_id: int, version_id: int, _: AdminAuth, service: DocumentServiceDep) -> DocumentVersion:
    return service.get_version(document_id, version_id)


@router.patch("/{document_id}/versions/{version_id}", response_model=DocumentVersion)
def update_version(
    document_id: int, version_id: int, body: DocumentVersionUpdateRequest, auth: AdminAuth, service: DocumentServiceDep,
) -> DocumentVersion:
    return service.update_version(document_id, version_id, body, auth.user)
