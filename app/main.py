import io
import zipfile
import logging
import mimetypes
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Header, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models import Token, User, Role, WatermarkRequest, DocumentInfo, DocumentListResponse
from .auth import (
    authenticate_user,
    fake_users_db,
    create_access_token,
    decode_jwt_token,
)
from .authorization import RoleChecker
from .watermark import apply_watermark



# Configure structured audit logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
audit_logger = logging.getLogger("audit")

app = FastAPI(
    title="Dynamic Digital Watermarking Engine - POC",
    description="High-security, in-memory PDF digital watermarking service.",
    version="1.0.0"
)

# CORS configuration for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Ensure static directory exists and mount static files
settings.STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")

# Role checker permitting ADMIN, TEACHER, and STUDENT
allow_authenticated_roles = RoleChecker([Role.ADMIN, Role.TEACHER, Role.STUDENT])

@app.get(
    "/",
    response_class=FileResponse,
    summary="Serve the web application frontend",
    tags=["Frontend"]
)
async def serve_index():
    index_file = settings.STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Frontend index.html not found"
        )
    return FileResponse(index_file, media_type="text/html")

@app.post(
    "/token",
    response_model=Token,
    summary="Authenticate and receive JWT token",
    tags=["Authentication"]
)
async def login_for_access_token(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends()
):
    user = authenticate_user(fake_users_db, form_data.username, form_data.password)
    if not user:
        audit_logger.warning(
            f"user={form_data.username} action=LOGIN status=FAILED reason=invalid_credentials"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.user_id,
            "role": user.role
        },
        expires_delta=access_token_expires
    )

    # Establish HttpOnly session cookie for browser SCORM navigation & sub-resource assets
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/"
    )

    audit_logger.info(
        f"user={user.username} user_id={user.user_id} role={user.role} action=LOGIN status=SUCCESS"
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post(
    "/logout",
    summary="Log out and clear session cookie",
    tags=["Authentication"]
)
async def logout_session(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"message": "Successfully logged out"}


def discover_scorm_pdf(package_dir: Path) -> Optional[Path]:
    """
    Recursively discovers the first valid PDF file inside a SCORM package directory.
    Ignores hidden files and directories.
    """
    if not package_dir.exists() or not package_dir.is_dir():
        return None
    for pdf_file in sorted(package_dir.rglob("*.pdf"), key=lambda p: p.name.lower()):
        # Exclude hidden files / dotfiles
        if any(part.startswith(".") for part in pdf_file.parts):
            continue
        if pdf_file.is_file():
            return pdf_file
    return None

def generate_dynamic_watermark_text(user: User) -> str:
    """
    Generates dynamic multi-line watermark text containing the authenticated user context
    and a fresh Indian Standard Time (IST) timestamp.
    """
    ist = ZoneInfo("Asia/Kolkata")
    ist_timestamp = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")
    return (
        f"CONFIDENTIAL — LICENSED TO: {user.username}\n"
        f"ID: {user.user_id}\n"
        f"{user.school_name}\n"
        f"{ist_timestamp}"
    )

def parse_scorm_manifest(manifest_path: Path) -> dict:
    """
    Parses imsmanifest.xml to extract title, organization name, and default entry point.
    """
    info = {
        "title": None,
        "organization": None,
        "entry_point": "index.html"
    }
    if not manifest_path.exists() or not manifest_path.is_file():
        return info

    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()

        for elem in root.iter():
            tag = elem.tag.lower()
            if tag.endswith("item") and not info["title"]:
                for child in elem:
                    if child.tag.lower().endswith("title") and child.text:
                        info["title"] = child.text.strip()
                        break
            elif tag.endswith("organization") and not info["organization"]:
                for child in elem:
                    if child.tag.lower().endswith("title") and child.text:
                        info["organization"] = child.text.strip()
                        break

        for elem in root.iter():
            if elem.tag.lower().endswith("resource"):
                href = elem.attrib.get("href")
                if href:
                    info["entry_point"] = href.strip()
                    break

    except Exception as parse_err:
        audit_logger.warning(f"Failed to parse SCORM manifest at {manifest_path}: {parse_err}")

    return info

@app.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List available PDF documents and SCORM packages in the content directory",
    tags=["Documents"]
)
async def list_documents(
    current_user: User = Depends(allow_authenticated_roles)
):
    """
    Scans the configured content/input directory and returns discovered PDF documents
    and validated SCORM packages. Excludes hidden files, non-PDF files, and non-SCORM directories.
    Never exposes server filesystem paths.
    """
    input_dir = settings.INPUT_DIR.resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        return DocumentListResponse(documents=[])

    documents: List[DocumentInfo] = []
    for item in sorted(input_dir.iterdir(), key=lambda p: p.name.lower()):
        # Exclude hidden files and directories
        if item.name.startswith("."):
            continue

        # 1. PDF Documents
        if item.is_file() and item.suffix.lower() == ".pdf":
            stat = item.stat()
            documents.append(
                DocumentInfo(
                    id=item.name,
                    name=item.name,
                    filename=item.name,
                    type="pdf",
                    size=stat.st_size,
                    modified_at=stat.st_mtime
                )
            )

        # 2. SCORM Packages (directories containing imsmanifest.xml)
        elif item.is_dir():
            manifest_file = item / "imsmanifest.xml"
            if manifest_file.exists() and manifest_file.is_file():
                manifest_data = parse_scorm_manifest(manifest_file)
                display_name = manifest_data.get("title") or item.name
                stat = item.stat()
                scorm_pdf = discover_scorm_pdf(item)
                pdf_filename = scorm_pdf.name if scorm_pdf else None
                has_pdf = scorm_pdf is not None

                documents.append(
                    DocumentInfo(
                        id=item.name,
                        name=display_name,
                        filename=item.name,
                        type="scorm",
                        title=display_name,
                        organization=manifest_data.get("organization"),
                        entry_point=manifest_data.get("entry_point") or "index.html",
                        pdf_filename=pdf_filename,
                        has_pdf=has_pdf,
                        modified_at=stat.st_mtime
                    )
                )

    return DocumentListResponse(documents=documents)

@app.get(
    "/scorm/{package_id}/pdf",
    response_class=Response,
    summary="Retrieve dynamically watermarked PDF located inside SCORM package (in-memory, zero-disk)",
    tags=["SCORM"]
)
@app.post(
    "/scorm/{package_id}/pdf",
    response_class=Response,
    summary="Retrieve dynamically watermarked PDF located inside SCORM package (in-memory, zero-disk)",
    tags=["SCORM"]
)
async def watermark_scorm_pdf(
    package_id: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Cookie(None)
):
    """
    Recursively discovers and applies dynamic in-memory watermark to the PDF inside a SCORM package.
    Authenticates via Authorization: Bearer <token> header, access_token cookie, or ?token= query parameter.
    Never modifies original file on disk; returns pure watermarked PDF bytes directly.
    """
    # 1. Authenticate user
    auth_token = None
    if authorization and authorization.startswith("Bearer "):
        auth_token = authorization.split("Bearer ", 1)[1].strip()
    elif access_token:
        auth_token = access_token.strip()
    elif token:
        auth_token = token.strip()

    if not auth_token:
        audit_logger.warning(f"package={package_id} action=SCORM_PDF_WATERMARK status=REJECTED reason=unauthenticated")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to access SCORM PDF content",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_user = decode_jwt_token(auth_token)
    allow_authenticated_roles(user=current_user)

    # 2. Path safety for package_id
    if not package_id or ".." in package_id or "/" in package_id or "\\" in package_id:
        audit_logger.warning(
            f"user={current_user.username} package={package_id} action=SCORM_PDF_WATERMARK status=REJECTED reason=invalid_package_id"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid SCORM package identifier"
        )

    input_dir = settings.INPUT_DIR.resolve()
    package_dir = (input_dir / package_id).resolve()

    if package_dir.parent != input_dir or not package_dir.exists() or not package_dir.is_dir():
        audit_logger.warning(
            f"user={current_user.username} package={package_id} action=SCORM_PDF_WATERMARK status=NOT_FOUND"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SCORM package '{package_id}' not found"
        )

    # 3. Recursively discover PDF inside SCORM package
    pdf_path = discover_scorm_pdf(package_dir)
    if not pdf_path or not pdf_path.exists() or not pdf_path.is_file():
        audit_logger.warning(
            f"user={current_user.username} package={package_id} action=SCORM_PDF_WATERMARK status=PDF_NOT_FOUND"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No PDF document found inside SCORM package '{package_id}'"
        )

    # 4. Read original PDF bytes into memory (read-only)
    try:
        pdf_bytes = pdf_path.read_bytes()
    except Exception as read_err:
        audit_logger.error(
            f"user={current_user.username} package={package_id} file={pdf_path.name} action=SCORM_PDF_WATERMARK status=READ_ERROR error={read_err}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read PDF from SCORM package"
        )

    # 5. Generate dynamic watermark string strictly from authenticated user context
    watermark_text = generate_dynamic_watermark_text(current_user)

    # 6. Apply watermark entirely in memory
    try:
        watermarked_bytes = apply_watermark(
            pdf_bytes=pdf_bytes,
            watermark_text=watermark_text,
            opacity=settings.WATERMARK_OPACITY
        )
    except Exception as wm_err:
        audit_logger.error(
            f"user={current_user.username} package={package_id} file={pdf_path.name} action=SCORM_PDF_WATERMARK status=ENGINE_ERROR error={wm_err}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to apply digital watermark to SCORM PDF"
        )

    # 7. Audit log success
    safe_filename = pdf_path.name
    audit_logger.info(
        f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
        f"package={package_id} document={safe_filename} action=SCORM_PDF_WATERMARK status=SUCCESS size={len(watermarked_bytes)}"
    )

    # 8. Return directly in HTTP response with proper disposition header
    return Response(
        content=watermarked_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="watermarked_{safe_filename}"'
        }
    )

@app.get(
    "/scorm/{package_id}/download",
    summary="Download SCORM package as a ZIP archive (in-memory, zero-disk)",
    tags=["SCORM"]
)
async def download_scorm_package(
    package_id: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Cookie(None)
):
    """
    Safely packages the requested SCORM package into an in-memory ZIP archive.
    Requires authentication via Authorization header, access_token cookie, or ?token= query parameter.
    Never persists the generated ZIP to disk (zero-disk requirement).
    """
    # 1. Authenticate user
    auth_token = None
    if authorization and authorization.startswith("Bearer "):
        auth_token = authorization.split("Bearer ", 1)[1].strip()
    elif access_token:
        auth_token = access_token.strip()
    elif token:
        auth_token = token.strip()

    if not auth_token:
        audit_logger.warning(f"package={package_id} action=SCORM_DOWNLOAD status=REJECTED reason=unauthenticated")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to download SCORM content",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_user = decode_jwt_token(auth_token)
    allow_authenticated_roles(user=current_user)

    # 2. Path safety for package_id
    if not package_id or ".." in package_id or "/" in package_id or "\\" in package_id:
        audit_logger.warning(
            f"user={current_user.username} package={package_id} action=SCORM_DOWNLOAD status=REJECTED reason=invalid_package_id"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid SCORM package identifier"
        )

    input_dir = settings.INPUT_DIR.resolve()
    package_dir = (input_dir / package_id).resolve()

    if package_dir.parent != input_dir or not package_dir.exists() or not package_dir.is_dir():
        audit_logger.warning(
            f"user={current_user.username} package={package_id} action=SCORM_DOWNLOAD status=NOT_FOUND"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SCORM package '{package_id}' not found"
        )

    # 3. Create ZIP entirely in memory using io.BytesIO and zipfile.ZipFile
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in package_dir.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                # Store relative to package_dir so ZIP extracts cleanly
                arcname = file_path.relative_to(package_dir)
                zf.write(file_path, arcname=str(arcname))

    zip_bytes = zip_buffer.getvalue()
    zip_buffer.close()

    audit_logger.info(
        f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
        f"package={package_id} action=SCORM_DOWNLOAD status=SUCCESS size={len(zip_bytes)}"
    )

    safe_pkg_name = Path(package_id).name
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_pkg_name}.zip"'
        }
    )

@app.get(
    "/scorm/{package_id}",
    summary="Launch SCORM package entry point",
    tags=["SCORM"]
)
@app.post(
    "/scorm/{package_id}",
    summary="Launch SCORM package entry point",
    tags=["SCORM"]
)
@app.get(
    "/scorm/{package_id}/{file_path:path}",
    summary="Serve protected SCORM package files",
    tags=["SCORM"]
)
@app.post(
    "/scorm/{package_id}/{file_path:path}",
    summary="Serve protected SCORM package files",
    tags=["SCORM"]
)
async def serve_scorm_package(
    package_id: str,
    file_path: str = "",
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    access_token: Optional[str] = Cookie(None)
):
    """
    Safely serves authenticated SCORM packages and sub-resources without path traversal.
    Authenticates via:
    1. Authorization: Bearer <token> header (API / automated clients)
    2. access_token HttpOnly cookie (Browser navigation / iframe / relative assets)
    3. ?token= query parameter (Fallback)
    """
    # 1. Authenticate user
    auth_token = None
    if authorization and authorization.startswith("Bearer "):
        auth_token = authorization.split("Bearer ", 1)[1].strip()
    elif access_token:
        auth_token = access_token.strip()
    elif token:
        auth_token = token.strip()

    if not auth_token:
        audit_logger.warning(f"package={package_id} action=SCORM_ACCESS status=REJECTED reason=unauthenticated")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to access SCORM content",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_user = decode_jwt_token(auth_token)
    allow_authenticated_roles(user=current_user)

    # 2. Path safety for package_id
    if not package_id or ".." in package_id or "/" in package_id or "\\" in package_id:
        audit_logger.warning(
            f"user={current_user.username} package={package_id} action=SCORM_ACCESS status=REJECTED reason=invalid_package_id"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid SCORM package identifier"
        )

    input_dir = settings.INPUT_DIR.resolve()
    package_dir = (input_dir / package_id).resolve()

    if package_dir.parent != input_dir or not package_dir.exists() or not package_dir.is_dir():
        audit_logger.warning(
            f"user={current_user.username} package={package_id} action=SCORM_ACCESS status=NOT_FOUND"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SCORM package '{package_id}' not found"
        )

    # Default to entry point if file_path is empty
    if not file_path or file_path.strip() == "":
        manifest_file = package_dir / "imsmanifest.xml"
        manifest_data = parse_scorm_manifest(manifest_file)
        file_path = manifest_data.get("entry_point") or "index.html"

    # Path safety for file_path
    if ".." in file_path or "\\" in file_path or file_path.startswith("/"):
        audit_logger.warning(
            f"user={current_user.username} package={package_id} file={file_path} action=SCORM_ACCESS status=REJECTED reason=path_traversal"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path in SCORM package"
        )

    target_file = (package_dir / file_path).resolve()

    # Ensure target_file is strictly within package_dir
    try:
        target_file.relative_to(package_dir)
    except ValueError:
        audit_logger.warning(
            f"user={current_user.username} package={package_id} file={file_path} action=SCORM_ACCESS status=REJECTED reason=out_of_bounds"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File path outside SCORM package boundaries"
        )

    if not target_file.exists() or not target_file.is_file():
        audit_logger.warning(
            f"user={current_user.username} package={package_id} file={file_path} action=SCORM_ACCESS status=NOT_FOUND"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{file_path}' not found in SCORM package"
        )

    # If requested file is a PDF document, dynamically apply in-memory watermark
    if target_file.suffix.lower() == ".pdf":
        try:
            pdf_bytes = target_file.read_bytes()
            watermark_text = generate_dynamic_watermark_text(current_user)
            watermarked_bytes = apply_watermark(
                pdf_bytes=pdf_bytes,
                watermark_text=watermark_text,
                opacity=settings.WATERMARK_OPACITY
            )
            audit_logger.info(
                f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
                f"package={package_id} document={target_file.name} action=SCORM_PDF_WATERMARK status=SUCCESS size={len(watermarked_bytes)}"
            )
            return Response(
                content=watermarked_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'inline; filename="watermarked_{target_file.name}"'
                }
            )
        except Exception as wm_err:
            audit_logger.error(
                f"user={current_user.username} package={package_id} file={target_file.name} action=SCORM_PDF_WATERMARK status=ENGINE_ERROR error={wm_err}"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to apply digital watermark to SCORM PDF"
            )

    media_type, _ = mimetypes.guess_type(str(target_file))
    if not media_type:
        media_type = "application/octet-stream"

    return FileResponse(target_file, media_type=media_type)



@app.post(
    "/watermark",
    response_class=Response,
    summary="Request a dynamic watermarked PDF from input directory (processed entirely in memory)",
    tags=["Watermark"]
)
async def watermark_pdf(
    request: WatermarkRequest,
    current_user: User = Depends(allow_authenticated_roles)
):
    filename = request.pdf_filename.strip()

    # 1. Strict path traversal & filename safety check
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK status=REJECTED reason=path_traversal_or_invalid_name"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: path traversal characters and directory separators are prohibited"
        )

    # 2. Extension validation
    if not filename.lower().endswith(".pdf"):
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK status=REJECTED reason=non_pdf_file"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type: only .pdf files are accepted"
        )

    # 3. Resolve path safely within configured input directory
    input_dir = settings.INPUT_DIR.resolve()
    target_path = (input_dir / filename).resolve()

    # Confirm path stays strictly within input_dir and exists as a regular file
    if target_path.parent != input_dir:
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK status=REJECTED reason=out_of_bounds_path"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path"
        )

    if not target_path.exists() or not target_path.is_file():
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK status=NOT_FOUND"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requested PDF '{filename}' was not found in the input repository"
        )

    # 4. Read original bytes into memory (read-only)
    try:
        pdf_bytes = target_path.read_bytes()
    except Exception as read_err:
        audit_logger.error(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK status=READ_ERROR error={read_err}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read the requested PDF file"
        )

    # 5. Generate dynamic watermark string strictly from authenticated context
    watermark_text = generate_dynamic_watermark_text(current_user)

    # 6. Apply watermark entirely in memory
    try:
        watermarked_bytes = apply_watermark(
            pdf_bytes=pdf_bytes,
            watermark_text=watermark_text,
            opacity=settings.WATERMARK_OPACITY
        )
    except Exception as wm_err:
        audit_logger.error(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK status=ENGINE_ERROR error={wm_err}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to apply digital watermark"
        )

    # 7. Audit log success
    audit_logger.info(
        f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
        f"document={filename} action=WATERMARK status=SUCCESS"
    )

    # 8. Return directly in HTTP response with appropriate disposition headers (never written to disk)
    return Response(
        content=watermarked_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="watermarked_{filename}"'
        }
    )

@app.post(
    "/watermark/upload",
    response_class=Response,
    summary="Upload a PDF and receive a dynamic watermarked copy (processed entirely in memory)",
    tags=["Watermark"]
)
async def watermark_pdf_upload(
    file: UploadFile = File(...),
    current_user: User = Depends(allow_authenticated_roles)
):
    raw_filename = file.filename or ""
    filename = raw_filename.strip()

    # 1. Filename validation & Path Traversal check
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK_UPLOAD status=REJECTED reason=path_traversal_or_invalid_name"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename: path traversal characters and directory separators are prohibited"
        )

    # 2. Extension validation
    if not filename.lower().endswith(".pdf"):
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK_UPLOAD status=REJECTED reason=non_pdf_file"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type: only .pdf files are accepted"
        )

    # 3. Read uploaded bytes directly into memory
    try:
        pdf_bytes = await file.read()
    except Exception as read_err:
        audit_logger.error(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK_UPLOAD status=READ_ERROR error={read_err}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read uploaded file"
        )

    # 4. Check file size against configured limit
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(pdf_bytes) > max_bytes:
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK_UPLOAD status=REJECTED reason=payload_too_large size={len(pdf_bytes)}"
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds maximum upload size of {settings.MAX_UPLOAD_SIZE_MB}MB"
        )

    if len(pdf_bytes) == 0:
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK_UPLOAD status=REJECTED reason=empty_file"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty"
        )

    # 5. Validate PDF header magic bytes
    if not pdf_bytes.startswith(b"%PDF"):
        audit_logger.warning(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK_UPLOAD status=REJECTED reason=invalid_pdf_header"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a valid PDF document"
        )

    # 6. Generate dynamic watermark string strictly from authenticated context
    watermark_text = generate_dynamic_watermark_text(current_user)

    # 7. Apply watermark entirely in memory
    try:
        watermarked_bytes = apply_watermark(
            pdf_bytes=pdf_bytes,
            watermark_text=watermark_text,
            opacity=settings.WATERMARK_OPACITY
        )
    except Exception as wm_err:
        audit_logger.error(
            f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
            f"document={filename} action=WATERMARK_UPLOAD status=ENGINE_ERROR error={wm_err}"
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failed to process and watermark the provided PDF file"
        )

    # 8. Audit log success
    safe_filename = Path(filename).name
    audit_logger.info(
        f"user={current_user.username} user_id={current_user.user_id} role={current_user.role} "
        f"document={safe_filename} action=WATERMARK_UPLOAD status=SUCCESS size={len(watermarked_bytes)}"
    )

    # 9. Return directly in HTTP response with appropriate disposition headers (never written to disk)
    return Response(
        content=watermarked_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="watermarked_{safe_filename}"'
        }
    )
