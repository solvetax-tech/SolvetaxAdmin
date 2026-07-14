import logging
import asyncpg
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends,status,UploadFile, File
from typing import Optional, List
from backend.security.rbac import require_permission
from backend.gst_registration.schemas import (
    RegistrationDocumentIn,
    RegistrationDocumentEditIn,
)
from backend.utils import get_db_pool, DB_SCHEMA, generate_uuid, get_blob_service_client, AZURE_STORAGE_CONTAINER, generate_blob_sas_url, extract_blob_path, build_gst_visibility
from backend.logger import logger
from backend.redis_cache import build_cache_key, get_or_set_json as redis_get_or_set_json
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
from urllib.parse import urlparse

router = APIRouter(
    prefix="/api/v1/gst-blob",
    tags=["GST Registration Blob"],
)


async def _authorize_gst_blob_access(blob_url: str, role, emp_id) -> bool:
    """
    Confirm the requested blob is a GST registration document the caller may
    see, BEFORE minting a SAS read/download URL.

    Without this, any EMPLOYEE:READ holder could pass an arbitrary blob path
    (or a leaked/guessed one) to /view or /download and receive a working SAS
    URL to any document in the container (an IDOR over PII). We require the URL
    to match a stored gst_registration_documents.document_url AND pass the same
    RM/OP visibility scoping used by the document list endpoints.
    """
    role_norm = str(role).strip().upper() if role else None
    vis_sql, vis_vals, _ = build_gst_visibility(role_norm, emp_id, 2, DB_SCHEMA)
    vis_clause = f"AND ({vis_sql})" if vis_sql else ""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        found = await conn.fetchval(
            f"""
            SELECT 1
            FROM {DB_SCHEMA}.gst_registration_documents d
            JOIN {DB_SCHEMA}.gst_registration_persons p
              ON d.person_id = p.person_id
            JOIN {DB_SCHEMA}.gst_registration g
              ON p.gst_registration_id = g.id
            WHERE d.document_url = $1
            {vis_clause}
            LIMIT 1
            """,
            blob_url,
            *vis_vals,
        )
    return bool(found)

# --------------------------------------------------
# UPLOAD REGISTRATION DOCUMENT
# --------------------------------------------------

@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload Registration Document File (Blob Only)",
    responses={
        201: {"description": "File uploaded successfully."},
        400: {"description": "Invalid file."},
        500: {"description": "Blob upload failed."},
    },
)
async def upload_registration_document_file(
    file: UploadFile = File(...),
    current_user=Depends(require_permission("EMPLOYEE", "WRITE")),
):

    # --------------------------------------------------
    # Local Upload Helper (Scoped to This API Only)
    # --------------------------------------------------

    def upload_file_to_blob(file_bytes: bytes, filename: str, folder: str = "gst-documents") -> str:
        """
        Upload file to Azure Blob Storage.
        Returns blob URL.
        """

        # Obtain singleton Azure Blob client
        blob_service_client = get_blob_service_client()

        # Generate unique filename to avoid collision
        unique_filename = f"{generate_uuid()}_{filename}"

        # Blob storage path
        blob_path = f"{folder}/{unique_filename}"

        # Create blob client instance
        blob_client = blob_service_client.get_blob_client(
            container=AZURE_STORAGE_CONTAINER,
            blob=blob_path,
        )

        # Upload file to Azure
        blob_client.upload_blob(file_bytes, overwrite=True)

        # Return accessible blob URL
        return blob_client.url


    # --------------------------------------------------
    # Request Context
    # --------------------------------------------------

    # Unique request tracking ID
    request_id = generate_uuid()

    # Extract employee identifier
    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")

    # Convert to integer safely
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    # Structured logger adapter
    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Incoming document file upload | filename=%s", file.filename)


    # --------------------------------------------------
    # File Validation
    # --------------------------------------------------

    # Allowed content types
    ALLOWED_TYPES = ["application/pdf", "image/jpeg", "image/png"]

    # Maximum allowed file size (10MB)
    MAX_FILE_SIZE = 2*5 * 1024 * 1024  # 10MB

    # Validate file type
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: PDF, JPG, PNG.",
        )

    # Read uploaded file
    contents = await file.read()

    # Validate file size
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 10MB limit.",
        )

    # Content-sniff via magic bytes — the client-supplied Content-Type above is
    # trusted for nothing; a caller could spoof image/png on an HTML/script
    # payload that would later be served inline. Require the actual bytes to
    # match one of the allowed signatures (PDF / JPEG / PNG).
    def _sniff_allowed(data: bytes) -> bool:
        if data.startswith(b"%PDF-"):
            return True
        if data.startswith(b"\xff\xd8\xff"):  # JPEG
            return True
        if data.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
            return True
        return False

    if not _sniff_allowed(contents):
        raise HTTPException(
            status_code=400,
            detail="File content does not match an allowed type (PDF, JPG, PNG).",
        )


    # --------------------------------------------------
    # Upload File to Azure Blob
    # --------------------------------------------------

    try:

        blob_url = upload_file_to_blob(contents, file.filename)

    except Exception:

        log.exception("Azure blob upload failed")

        raise HTTPException(
            status_code=500,
            detail="Blob upload failed.",
        )


    # --------------------------------------------------
    # Success Response
    # --------------------------------------------------

    log.info("File uploaded successfully | blob_url=%s", blob_url)

    return {
        "blob_url": blob_url,
        "filename": file.filename,
        "message": "File uploaded successfully.",
        "request_id": request_id,
    }


# --------------------------------------------------
# VIEW GST DOCUMENT (SAS URL GENERATION)
# --------------------------------------------------

@router.get(
    "/view",
    summary="View GST Document",
    responses={
        200: {"description": "Secure view URL generated"},
        400: {"description": "Invalid blob URL"},
        500: {"description": "Unable to generate view link"},
    },
)
async def view_registration_document(
    blob_url: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Generating secure VIEW URL | blob_url=%s", blob_url)

    # Authorization gate (IDOR guard): the blob must be a GST document this
    # employee is allowed to see. Runs before the cache so it always executes.
    if not await _authorize_gst_blob_access(blob_url, current_user.get("role"), emp_id):
        log.warning("Blob view denied — not an authorized document | blob_url=%s", blob_url)
        raise HTTPException(status_code=404, detail="Document not found.")

    cache_key = build_cache_key(
        "gst_blob:view",
        blob_url=blob_url,
        emp_id=emp_id,
    )

    async def _load_view_registration_document():
        try:

            blob_path = extract_blob_path(blob_url)

            # inline -> preview in browser
            sas_url = generate_blob_sas_url(blob_path, disposition="inline")

            log.info("View URL generated successfully | blob=%s", blob_path)

        except ValueError as e:

            log.error("Invalid blob URL | error=%s", str(e))

            raise HTTPException(
                status_code=400,
                detail="Invalid blob URL provided",
            )

        except Exception:

            log.exception("Failed generating view URL")

            raise HTTPException(
                status_code=500,
                detail="Unable to generate document view link",
            )

        return {
            "view_url": sas_url,
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_view_registration_document,
        ttl_seconds=300,
        tags=["gst_blob:view:index"],
    )

    # --------------------------------------------------
# DOWNLOAD GST DOCUMENT (SAS URL GENERATION)
# --------------------------------------------------

@router.get(
    "/download",
    summary="Download GST Document",
    responses={
        200: {"description": "Secure download URL generated"},
        400: {"description": "Invalid blob URL"},
        500: {"description": "Unable to generate download link"},
    },
)
async def download_registration_document(
    blob_url: str,
    current_user=Depends(require_permission("EMPLOYEE", "READ")),
):

    request_id = generate_uuid()

    emp_id_raw = current_user.get("emp_id") or current_user.get("sub")
    emp_id = int(emp_id_raw) if str(emp_id_raw).isdigit() else None

    log = logging.LoggerAdapter(
        logger,
        {"request_id": request_id, "emp_id": emp_id},
    )

    log.info("Generating secure DOWNLOAD URL | blob_url=%s", blob_url)

    # Authorization gate (IDOR guard) — see view endpoint.
    if not await _authorize_gst_blob_access(blob_url, current_user.get("role"), emp_id):
        log.warning("Blob download denied — not an authorized document | blob_url=%s", blob_url)
        raise HTTPException(status_code=404, detail="Document not found.")

    cache_key = build_cache_key(
        "gst_blob:download",
        blob_url=blob_url,
        emp_id=emp_id,
    )

    async def _load_download_registration_document():
        try:

            blob_path = extract_blob_path(blob_url)

            # attachment -> download
            sas_url = generate_blob_sas_url(blob_path, disposition="attachment")

            log.info("Download URL generated successfully | blob=%s", blob_path)

        except ValueError as e:

            log.error("Invalid blob URL | error=%s", str(e))

            raise HTTPException(
                status_code=400,
                detail="Invalid blob URL provided",
            )

        except Exception:

            log.exception("Failed generating download URL")

            raise HTTPException(
                status_code=500,
                detail="Unable to generate document download link",
            )

        return {
            "download_url": sas_url,
            "request_id": request_id,
        }

    return await redis_get_or_set_json(
        cache_key,
        loader=_load_download_registration_document,
        ttl_seconds=300,
        tags=["gst_blob:download:index"],
    )