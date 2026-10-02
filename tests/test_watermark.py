import io
import zipfile
import hashlib
import logging
from unittest.mock import patch
from pathlib import Path
import pytest
import pymupdf
from fastapi.testclient import TestClient

from app.main import app
from app.watermark import apply_watermark
from app.config import settings

client = TestClient(app)

def create_in_memory_test_pdf(pages: int = 2, landscape: bool = False) -> bytes:
    """
    Creates a small in-memory PDF entirely in RAM for unit testing.
    Never persists to disk.
    """
    doc = pymupdf.open()
    for i in range(pages):
        rect = pymupdf.Rect(0, 0, 842, 595) if landscape else pymupdf.Rect(0, 0, 595, 842)
        page = doc.new_page(width=rect.width, height=rect.height)
        page.insert_text(pymupdf.Point(50, 50), f"Sample Page {i + 1} Content")
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes

# ==========================================
# WATERMARK ENGINE TESTS (19 - 26)
# ==========================================

def test_19_watermark_accepts_pdf_bytes():
    """19. apply_watermark accepts raw PDF bytes as input."""
    raw_pdf = create_in_memory_test_pdf(pages=1)
    assert isinstance(raw_pdf, bytes)
    output = apply_watermark(raw_pdf, "Test Watermark", opacity=0.20)
    assert output is not None

def test_20_watermark_output_is_valid_pdf():
    """20. apply_watermark produces a valid, readable PDF document."""
    raw_pdf = create_in_memory_test_pdf(pages=2)
    output = apply_watermark(raw_pdf, "Confidential - ID: USR-001", opacity=0.20)
    
    doc = pymupdf.open(stream=io.BytesIO(output), filetype="pdf")
    assert doc.is_pdf
    assert doc.page_count == 2
    doc.close()

def test_21_watermark_output_is_bytes():
    """21. apply_watermark output is strictly of type bytes."""
    raw_pdf = create_in_memory_test_pdf(pages=1)
    output = apply_watermark(raw_pdf, "Watermark Text")
    assert isinstance(output, bytes)
    assert len(output) > 0

def test_22_page_count_preserved():
    """22. Page count of the watermarked PDF exactly matches the original."""
    raw_pdf = create_in_memory_test_pdf(pages=5)
    doc_in = pymupdf.open(stream=io.BytesIO(raw_pdf), filetype="pdf")
    count_in = doc_in.page_count
    doc_in.close()

    output = apply_watermark(raw_pdf, "Confidential - ID: 123")
    doc_out = pymupdf.open(stream=io.BytesIO(output), filetype="pdf")
    count_out = doc_out.page_count
    doc_out.close()

    assert count_in == count_out == 5

def test_23_watermark_appears_on_every_page():
    """23. Watermark text appears on every page of multi-page documents."""
    raw_pdf = create_in_memory_test_pdf(pages=3)
    watermark_str = "WATERMARK"
    output = apply_watermark(raw_pdf, watermark_str)

    doc_out = pymupdf.open(stream=io.BytesIO(output), filetype="pdf")
    assert doc_out.page_count == 3
    for i in range(doc_out.page_count):
        page_text = doc_out[i].get_text()
        assert watermark_str in page_text, f"Watermark missing on page {i + 1}"
    doc_out.close()

def test_24_original_pdf_bytes_unchanged():
    """24. Original PDF byte array is immutable and untouched."""
    raw_pdf = create_in_memory_test_pdf(pages=2)
    original_copy = bytes(raw_pdf)

    _ = apply_watermark(raw_pdf, "Confidential - ID: 123")

    assert raw_pdf == original_copy

def test_25_multiple_page_sizes_handled():
    """25. Engine seamlessly processes portrait, landscape, and mixed page sizes."""
    portrait_pdf = create_in_memory_test_pdf(pages=2, landscape=False)
    out_portrait = apply_watermark(portrait_pdf, "Portrait Watermark")
    assert len(out_portrait) > 0

    landscape_pdf = create_in_memory_test_pdf(pages=2, landscape=True)
    out_landscape = apply_watermark(landscape_pdf, "Landscape Watermark")
    assert len(out_landscape) > 0

def test_26_opacity_configuration_works():
    """26. Opacity configuration parameter is accepted and executed."""
    raw_pdf = create_in_memory_test_pdf(pages=1)
    output_faint = apply_watermark(raw_pdf, "Faint Watermark", opacity=0.10)
    output_bold = apply_watermark(raw_pdf, "Bold Watermark", opacity=0.80)
    assert isinstance(output_faint, bytes)
    assert isinstance(output_bold, bytes)

# ==========================================
# ENDPOINT & INTEGRATION TESTS (27 - 33)
# ==========================================

@pytest.fixture
def test_token():
    resp = client.post("/token", data={"username": "admin1", "password": "adminpass"})
    return resp.json()["access_token"]

def test_27_authenticated_request_succeeds(test_token):
    """27. Authenticated request for existing PDF succeeds with HTTP 200."""
    dummy_pdf = create_in_memory_test_pdf(pages=2)
    
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "is_file", return_value=True), \
         patch.object(Path, "read_bytes", return_value=dummy_pdf):
        
        response = client.post(
            "/watermark",
            headers={"Authorization": f"Bearer {test_token}"},
            json={"pdf_filename": "test_document.pdf"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment; filename=\"watermarked_test_document.pdf\"" in response.headers["content-disposition"]
        assert len(response.content) > 0

def test_28_unauthenticated_request_fails():
    """28. Unauthenticated request fails with HTTP 401."""
    response = client.post(
        "/watermark",
        json={"pdf_filename": "any_document.pdf"}
    )
    assert response.status_code == 401

def test_29_unauthorized_role_fails():
    """29. User with an unpermitted role is rejected."""
    from app.authorization import RoleChecker
    from app.models import User, Role
    from fastapi import HTTPException
    
    checker = RoleChecker([Role.ADMIN])
    student_user = User(
        username="student1",
        user_id="USR-003",
        school_name="Excelsoft Academy",
        role=Role.STUDENT
    )
    with pytest.raises(HTTPException) as exc:
        checker(user=student_user)
    assert exc.value.status_code == 403

def test_30_response_content_type_is_pdf(test_token):
    """30. Response content-type header is strictly application/pdf."""
    dummy_pdf = create_in_memory_test_pdf(pages=1)
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "is_file", return_value=True), \
         patch.object(Path, "read_bytes", return_value=dummy_pdf):
        
        response = client.post(
            "/watermark",
            headers={"Authorization": f"Bearer {test_token}"},
            json={"pdf_filename": "sample.pdf"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

def test_31_generated_pdf_not_written_to_output(test_token):
    """31. Generated watermarked PDF is never written to output/ directory."""
    dummy_pdf = create_in_memory_test_pdf(pages=1)
    output_dir = Path(__file__).resolve().parent.parent / "output"
    
    files_before = set(output_dir.glob("*.pdf"))

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "is_file", return_value=True), \
         patch.object(Path, "read_bytes", return_value=dummy_pdf):
        
        response = client.post(
            "/watermark",
            headers={"Authorization": f"Bearer {test_token}"},
            json={"pdf_filename": "output_check.pdf"}
        )
        assert response.status_code == 200

    files_after = set(output_dir.glob("*.pdf"))
    assert files_before == files_after == set()

def test_32_audit_log_is_generated(test_token, caplog):
    """32. Audit log is emitted containing user ID, document, and SUCCESS status."""
    dummy_pdf = create_in_memory_test_pdf(pages=1)
    
    with caplog.at_level(logging.INFO, logger="audit"):
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_bytes", return_value=dummy_pdf):
            
            response = client.post(
                "/watermark",
                headers={"Authorization": f"Bearer {test_token}"},
                json={"pdf_filename": "audit_test.pdf"}
            )
            assert response.status_code == 200
    
    assert any(
        "action=WATERMARK status=SUCCESS" in record.message for record in caplog.records
    )
    assert any("USR-001" in record.message for record in caplog.records)

def test_33_password_and_jwt_not_present_in_logs(test_token, caplog):
    """33. Audit log strictly omits passwords, JWT tokens, and sensitive credentials."""
    dummy_pdf = create_in_memory_test_pdf(pages=1)
    
    with caplog.at_level(logging.INFO):
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "is_file", return_value=True), \
             patch.object(Path, "read_bytes", return_value=dummy_pdf):
            
            _ = client.post(
                "/watermark",
                headers={"Authorization": f"Bearer {test_token}"},
                json={"pdf_filename": "sensitive_log_test.pdf"}
            )

    for record in caplog.records:
        assert "adminpass" not in record.message
        assert test_token not in record.message
        assert "Bearer" not in record.message

# ==========================================
# WEB APP & UPLOAD ENDPOINT TESTS (34 - 43)
# ==========================================

def test_34_root_serves_html():
    """34. GET / returns HTML web frontend."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Dynamic Digital Watermarking Engine" in response.text

def test_35_upload_pdf_success(test_token):
    """35. POST /watermark/upload with valid token and PDF returns 200 OK and PDF bytes."""
    dummy_pdf = create_in_memory_test_pdf(pages=2)
    files = {"file": ("my_upload.pdf", io.BytesIO(dummy_pdf), "application/pdf")}
    
    response = client.post(
        "/watermark/upload",
        headers={"Authorization": f"Bearer {test_token}"},
        files=files
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment; filename=\"watermarked_my_upload.pdf\"" in response.headers["content-disposition"]
    assert len(response.content) > 0

def test_36_upload_unauthenticated():
    """36. POST /watermark/upload without token returns HTTP 401."""
    dummy_pdf = create_in_memory_test_pdf(pages=1)
    files = {"file": ("my_upload.pdf", io.BytesIO(dummy_pdf), "application/pdf")}
    
    response = client.post(
        "/watermark/upload",
        files=files
    )
    assert response.status_code == 401

def test_37_upload_invalid_extension(test_token):
    """37. POST /watermark/upload with non-PDF extension is rejected with HTTP 400."""
    files = {"file": ("document.txt", io.BytesIO(b"Hello text"), "text/plain")}
    
    response = client.post(
        "/watermark/upload",
        headers={"Authorization": f"Bearer {test_token}"},
        files=files
    )
    assert response.status_code == 400
    assert "only .pdf files" in response.json()["detail"]

def test_38_upload_invalid_pdf_header(test_token):
    """38. POST /watermark/upload with fake/corrupt PDF header is rejected with HTTP 400."""
    files = {"file": ("fake.pdf", io.BytesIO(b"NOT_A_REAL_PDF_HEADER"), "application/pdf")}
    
    response = client.post(
        "/watermark/upload",
        headers={"Authorization": f"Bearer {test_token}"},
        files=files
    )
    assert response.status_code == 400
    assert "not a valid PDF" in response.json()["detail"]

def test_39_upload_oversized_file(test_token):
    """39. POST /watermark/upload with oversized content returns HTTP 413."""
    # Temporarily simulate small limit
    with patch.object(settings, "MAX_UPLOAD_SIZE_MB", 0):  # 0MB limit
        dummy_pdf = create_in_memory_test_pdf(pages=1)
        files = {"file": ("large.pdf", io.BytesIO(dummy_pdf), "application/pdf")}
        
        response = client.post(
            "/watermark/upload",
            headers={"Authorization": f"Bearer {test_token}"},
            files=files
        )
        assert response.status_code == 413
        assert "exceeds maximum upload size" in response.json()["detail"]

def test_40_upload_output_directory_remains_empty(test_token):
    """40. POST /watermark/upload does not write any files to output/."""
    dummy_pdf = create_in_memory_test_pdf(pages=2)
    files = {"file": ("zero_disk_upload.pdf", io.BytesIO(dummy_pdf), "application/pdf")}
    output_dir = Path(__file__).resolve().parent.parent / "output"

    files_before = set(output_dir.glob("*.pdf"))
    response = client.post(
        "/watermark/upload",
        headers={"Authorization": f"Bearer {test_token}"},
        files=files
    )
    assert response.status_code == 200
    files_after = set(output_dir.glob("*.pdf"))
    assert files_before == files_after == set()

def test_41_upload_audit_logging(test_token, caplog):
    """41. POST /watermark/upload logs audit information."""
    dummy_pdf = create_in_memory_test_pdf(pages=1)
    files = {"file": ("audit_upload.pdf", io.BytesIO(dummy_pdf), "application/pdf")}

    with caplog.at_level(logging.INFO, logger="audit"):
        response = client.post(
            "/watermark/upload",
            headers={"Authorization": f"Bearer {test_token}"},
            files=files
        )
        assert response.status_code == 200

    assert any(
        "action=WATERMARK_UPLOAD status=SUCCESS" in record.message for record in caplog.records
    )

def test_42_real_input_pdf_immutability(test_token):
    """42. Verifies that real input PDF on disk (if present) is not modified."""
    real_pdf_path = settings.INPUT_DIR / "100ques.pdf"
    if real_pdf_path.exists() and real_pdf_path.is_file():
        # Compute SHA-256 before request
        hash_before = hashlib.sha256(real_pdf_path.read_bytes()).hexdigest()
        
        # Execute watermark request
        response = client.post(
            "/watermark",
            headers={"Authorization": f"Bearer {test_token}"},
            json={"pdf_filename": "100ques.pdf"}
        )
        assert response.status_code == 200
        
        # Compute SHA-256 after request
        hash_after = hashlib.sha256(real_pdf_path.read_bytes()).hexdigest()
        assert hash_before == hash_after

# ==========================================
# DOCUMENT LISTING ENDPOINT TESTS (43 - 48)
# ==========================================

def test_43_get_documents_requires_authentication():
    """43. GET /documents without token is rejected with HTTP 401."""
    response = client.get("/documents")
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]

def test_44_get_documents_returns_pdf_list(test_token):
    """44. GET /documents with valid token returns 200 OK with PDFs and SCORM packages."""
    response = client.get(
        "/documents",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    docs = data["documents"]
    assert isinstance(docs, list)
    types = [d["type"] for d in docs]
    assert "pdf" in types
    pdf_docs = [d for d in docs if d["type"] == "pdf"]
    for doc in pdf_docs:
        assert doc["filename"].lower().endswith(".pdf")
        assert doc["size"] > 0

def test_45_get_documents_excludes_hidden_files_and_gitkeep(test_token):
    """45. GET /documents excludes .gitkeep and any dotfiles."""
    response = client.get(
        "/documents",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    filenames = [d.get("filename") or d["id"] for d in data["documents"]]
    assert ".gitkeep" not in filenames
    assert not any(f.startswith(".") for f in filenames)

def test_46_get_documents_excludes_arbitrary_non_scorm_directories(test_token, tmp_path):
    """46. GET /documents excludes folders that lack imsmanifest.xml."""
    # Create a temp directory with a dummy folder without manifest
    dummy_dir = tmp_path / "regular_folder"
    dummy_dir.mkdir()
    (tmp_path / "sample.pdf").write_bytes(create_in_memory_test_pdf(pages=1))
    
    with patch.object(settings, "INPUT_DIR", tmp_path):
        response = client.get(
            "/documents",
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 200
        docs = response.json()["documents"]
        ids = [d["id"] for d in docs]
        assert "regular_folder" not in ids
        assert "sample.pdf" in ids

def test_47_get_documents_excludes_non_pdf_files(test_token, tmp_path):
    """47. GET /documents strictly filters out non-PDF files."""
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / "valid.pdf").write_bytes(create_in_memory_test_pdf(pages=1))
    
    with patch.object(settings, "INPUT_DIR", tmp_path):
        response = client.get(
            "/documents",
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 200
        docs = response.json()["documents"]
        ids = [d["id"] for d in docs]
        assert "notes.txt" not in ids
        assert "valid.pdf" in ids

def test_48_get_documents_does_not_expose_filesystem_paths(test_token):
    """48. GET /documents returns only simple identifiers, never leaking server directory paths."""
    response = client.get(
        "/documents",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    data = response.json()
    for doc in data["documents"]:
        name = doc["id"]
        assert "/" not in name
        assert "\\" not in name
        assert ".." not in name
        assert "Users" not in name
        assert "input" not in name

def test_49_get_documents_empty_directory(test_token, tmp_path):
    """49. GET /documents returns empty list when no PDFs are in the directory."""
    with patch.object(settings, "INPUT_DIR", tmp_path):
        response = client.get(
            "/documents",
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert data["documents"] == []

# ==========================================
# LARGE DIAGONAL WATERMARK ENGINE TESTS (50 - 53)
# ==========================================

def test_50_watermark_multi_line_dynamic_formatting():
    """50. Multi-line pipe-separated watermark text is split and rendered on all pages."""
    raw_pdf = create_in_memory_test_pdf(pages=2)
    wm_text = "Confidential - Licensed to: teacher1 (ID: USR-002) | Excelsoft Academy | 2026-09-22 15:00:00 UTC"
    output = apply_watermark(raw_pdf, wm_text, opacity=0.25)
    
    doc = pymupdf.open(stream=io.BytesIO(output), filetype="pdf")
    assert doc.page_count == 2
    for page in doc:
        text = page.get_text()
        assert "CONFIDENTIAL" in text
        assert "teacher1" in text
        assert "USR-002" in text
        assert "Excelsoft Academy" in text
    doc.close()

def test_51_watermark_scales_for_portrait_and_landscape():
    """51. Dynamic font sizing scales proportionally for both portrait and landscape pages."""
    portrait_pdf = create_in_memory_test_pdf(pages=1, landscape=False)
    landscape_pdf = create_in_memory_test_pdf(pages=1, landscape=True)
    
    wm_text = "Confidential - Licensed to: student1 (ID: USR-003) | Excelsoft Academy | 2026-09-22 15:00:00 UTC"
    
    out_portrait = apply_watermark(portrait_pdf, wm_text)
    out_landscape = apply_watermark(landscape_pdf, wm_text)
    
    doc_p = pymupdf.open(stream=io.BytesIO(out_portrait), filetype="pdf")
    doc_l = pymupdf.open(stream=io.BytesIO(out_landscape), filetype="pdf")
    
    assert "student1" in doc_p[0].get_text()
    assert "student1" in doc_l[0].get_text()
    
    doc_p.close()
    doc_l.close()

def test_52_scorm_package_is_discovered_as_scorm_type(test_token):
    """52. Specific check that neema-scorm-1.2 package is discovered as type=scorm with title."""
    response = client.get(
        "/documents",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    docs = response.json()["documents"]
    scorm_docs = [d for d in docs if d["id"] == "neema-scorm-1.2"]
    assert len(scorm_docs) == 1
    scorm_pkg = scorm_docs[0]
    assert scorm_pkg["type"] == "scorm"
    assert "Neema" in (scorm_pkg.get("title") or scorm_pkg["name"])
    assert scorm_pkg["entry_point"] == "index.html"

def test_53_watermark_custom_opacity_respected():
    """53. Custom opacity parameter (e.g. 0.35) is executed without errors."""
    raw_pdf = create_in_memory_test_pdf(pages=1)
    output = apply_watermark(raw_pdf, "CONFIDENTIAL", opacity=0.35)
    assert isinstance(output, bytes)
    assert len(output) > len(raw_pdf)

# ==========================================
# SCORM SECURE SERVING TESTS (54 - 66)
# ==========================================

def test_54_scorm_endpoint_requires_authentication():
    """54. GET /scorm/neema-scorm-1.2 without token or cookie returns HTTP 401."""
    fresh_client = TestClient(app)
    response = fresh_client.get("/scorm/neema-scorm-1.2/index.html")
    assert response.status_code == 401
    assert "Authentication required" in response.json()["detail"]

def test_55_scorm_endpoint_serves_entry_point_with_header(test_token):
    """55. GET /scorm/neema-scorm-1.2 with Authorization header serves index.html."""
    fresh_client = TestClient(app)
    response = fresh_client.get(
        "/scorm/neema-scorm-1.2",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Neema" in response.text

def test_56_scorm_endpoint_serves_subresource_with_cookie(test_token):
    """56. GET /scorm/neema-scorm-1.2/css/style.css with access_token cookie serves CSS asset."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/neema-scorm-1.2/css/style.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]

def test_57_scorm_endpoint_serves_javascript_with_cookie(test_token):
    """57. GET /scorm/neema-scorm-1.2/js/scorm.js with access_token cookie serves JS asset."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/neema-scorm-1.2/js/scorm.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]

def test_58_scorm_endpoint_serves_images_with_cookie(test_token):
    """58. GET /scorm/neema-scorm-1.2/images/page-01.png with cookie serves image."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/neema-scorm-1.2/images/page-01.png")
    assert response.status_code == 200
    assert "image/png" in response.headers["content-type"]
    assert len(response.content) > 0

def test_59_scorm_endpoint_serves_lessons_and_quiz_with_cookie(test_token):
    """59. GET /scorm/neema-scorm-1.2/lessons/lesson1.html and quiz with cookie succeeds."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    res_lesson = fresh_client.get("/scorm/neema-scorm-1.2/lessons/lesson1.html")
    assert res_lesson.status_code == 200
    assert "text/html" in res_lesson.headers["content-type"]

    res_quiz = fresh_client.get("/scorm/neema-scorm-1.2/quiz/quiz.html")
    assert res_quiz.status_code == 200
    assert "text/html" in res_quiz.headers["content-type"]

def test_60_scorm_endpoint_path_traversal_rejected(test_token):
    """60. Path traversal attempts on /scorm are rejected with HTTP 400."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/..%2Fsecret/index.html")
    assert response.status_code == 400

    response2 = fresh_client.get("/scorm/neema-scorm-1.2/%2e%2e%2f100ques.pdf")
    assert response2.status_code == 400

def test_61_scorm_endpoint_missing_file_returns_404(test_token):
    """61. Nonexistent file in SCORM package returns HTTP 404."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/neema-scorm-1.2/non_existent_file.html")
    assert response.status_code == 404

def test_62_scorm_invalid_package_returns_404(test_token):
    """62. Nonexistent SCORM package returns HTTP 404."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/non_existent_package/index.html")
    assert response.status_code == 404

def test_63_login_sets_httponly_cookie():
    """63. POST /token sets access_token HttpOnly cookie."""
    fresh_client = TestClient(app)
    response = fresh_client.post(
        "/token",
        data={"username": "student1", "password": "studentpass"}
    )
    assert response.status_code == 200
    assert "access_token" in response.cookies
    # Verify cookie attributes
    cookie_header = response.headers.get("set-cookie", "")
    assert "httponly" in cookie_header.lower()
    assert "samesite=lax" in cookie_header.lower()

def test_64_logout_clears_cookie():
    """64. POST /logout clears the access_token session cookie."""
    fresh_client = TestClient(app)
    response = fresh_client.post("/logout")
    assert response.status_code == 200
    cookie_header = response.headers.get("set-cookie", "")
    # Should delete cookie (max-age=0 or expires in past)
    assert 'access_token=""' in cookie_header or "Max-Age=0" in cookie_header

def test_65_student_and_teacher_can_access_scorm():
    """65. Authenticated student and teacher roles can access SCORM content."""
    for user, pwd in [("student1", "studentpass"), ("teacher1", "teacherpass")]:
        login_client = TestClient(app)
        login_resp = login_client.post("/token", data={"username": user, "password": pwd})
        token = login_resp.json()["access_token"]
        scorm_client = TestClient(app, cookies={"access_token": token})
        scorm_resp = scorm_client.get("/scorm/neema-scorm-1.2/index.html")
        assert scorm_resp.status_code == 200

def test_66_scorm_download_requires_authentication():
    """66. GET /scorm/neema-scorm-1.2/download without authentication returns HTTP 401."""
    fresh_client = TestClient(app)
    response = fresh_client.get("/scorm/neema-scorm-1.2/download")
    assert response.status_code == 401
    assert "Authentication required" in response.json()["detail"]

def test_67_scorm_download_success_with_cookie(test_token):
    """67. GET /scorm/neema-scorm-1.2/download with cookie returns valid in-memory ZIP archive."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/neema-scorm-1.2/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert 'attachment; filename="neema-scorm-1.2.zip"' in response.headers["content-disposition"]
    
    # Verify ZIP validity and contents in memory
    zip_bytes = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        namelist = zf.namelist()
        assert "imsmanifest.xml" in namelist
        assert "index.html" in namelist
        assert "css/style.css" in namelist
        assert "js/scorm.js" in namelist
        assert "images/page-01.png" in namelist

def test_68_scorm_download_success_with_header(test_token):
    """68. GET /scorm/neema-scorm-1.2/download with Authorization header returns 200 and ZIP."""
    fresh_client = TestClient(app)
    response = fresh_client.get(
        "/scorm/neema-scorm-1.2/download",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert len(response.content) > 0

def test_69_scorm_download_path_traversal_rejected(test_token):
    """69. Path traversal attempts on /scorm/{package_id}/download are rejected with HTTP 400."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/..%2Fsecret/download")
    assert response.status_code == 400

def test_70_scorm_download_missing_package_returns_404(test_token):
    """70. Nonexistent package download returns HTTP 404."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/nonexistent-package/download")
    assert response.status_code == 404

def test_71_scorm_download_zero_disk_output(test_token):
    """71. SCORM package ZIP download does not write any files to output/."""
    output_dir = Path(__file__).resolve().parent.parent / "output"
    files_before = {f.name for f in output_dir.glob("*") if f.name != ".gitkeep"}

    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/neema-scorm-1.2/download")
    assert response.status_code == 200

    files_after = {f.name for f in output_dir.glob("*") if f.name != ".gitkeep"}
    assert files_before == files_after == set()

# ==========================================
# SCORM EMBEDDED PDF WATERMARKING TESTS (72 - 81)
# ==========================================

def test_72_scorm_pdf_discovery_in_documents(test_token):
    """72. GET /documents discovers embedded PDF inside SCORM package."""
    fresh_client = TestClient(app)
    response = fresh_client.get(
        "/documents",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    docs = response.json()["documents"]
    scorm_doc = next(d for d in docs if d["id"] == "neema-scorm-1.2")
    assert scorm_doc["has_pdf"] is True
    assert scorm_doc["pdf_filename"] == "neema-book.pdf"

def test_73_scorm_pdf_watermark_unauthenticated_rejected():
    """73. POST /scorm/neema-scorm-1.2/pdf without authentication is rejected with HTTP 401."""
    fresh_client = TestClient(app)
    response = fresh_client.post("/scorm/neema-scorm-1.2/pdf")
    assert response.status_code == 401
    assert "Authentication required" in response.json()["detail"]

def test_74_scorm_pdf_watermark_post_success(test_token):
    """74. POST /scorm/neema-scorm-1.2/pdf with JWT returns 200 and watermarked PDF."""
    fresh_client = TestClient(app)
    response = fresh_client.post(
        "/scorm/neema-scorm-1.2/pdf",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="watermarked_neema-book.pdf"' in response.headers["content-disposition"]
    assert len(response.content) > 0

    # Verify returned bytes form a valid PDF
    doc = pymupdf.open(stream=io.BytesIO(response.content), filetype="pdf")
    assert doc.is_pdf
    assert doc.page_count > 0
    doc.close()

def test_75_scorm_pdf_watermark_get_success(test_token):
    """75. GET /scorm/neema-scorm-1.2/pdf with cookie returns 200 and watermarked PDF."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/neema-scorm-1.2/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert len(response.content) > 0

def test_76_scorm_pdf_watermark_contains_user_claims():
    """76. Watermark applied to SCORM PDF dynamically contains user's identity on all pages."""
    login_client = TestClient(app)
    login_resp = login_client.post("/token", data={"username": "student1", "password": "studentpass"})
    token = login_resp.json()["access_token"]

    wm_client = TestClient(app)
    response = wm_client.post(
        "/scorm/neema-scorm-1.2/pdf",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200

    doc = pymupdf.open(stream=io.BytesIO(response.content), filetype="pdf")
    assert doc.page_count > 0
    for page in doc:
        page_text = page.get_text()
        assert "CONFIDENTIAL" in page_text
        assert "student1" in page_text
        assert "USR-003" in page_text
        assert "Excelsoft Academy" in page_text
    doc.close()

def test_77_scorm_pdf_watermark_path_traversal_rejected(test_token):
    """77. Path traversal attempts on /scorm/{package_id}/pdf are rejected with HTTP 400."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.post("/scorm/..%2Fsecret/pdf")
    assert response.status_code == 400

def test_78_scorm_pdf_watermark_nonexistent_package(test_token):
    """78. Nonexistent package for PDF watermarking returns HTTP 404."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.post("/scorm/nonexistent-package/pdf")
    assert response.status_code == 404

def test_79_scorm_pdf_watermark_original_file_immutability(test_token):
    """79. Original neema-book.pdf on disk remains strictly untouched."""
    real_scorm_pdf = settings.INPUT_DIR / "neema-scorm-1.2" / "neema-book.pdf"
    if real_scorm_pdf.exists() and real_scorm_pdf.is_file():
        hash_before = hashlib.sha256(real_scorm_pdf.read_bytes()).hexdigest()

        fresh_client = TestClient(app)
        response = fresh_client.post(
            "/scorm/neema-scorm-1.2/pdf",
            headers={"Authorization": f"Bearer {test_token}"}
        )
        assert response.status_code == 200

        hash_after = hashlib.sha256(real_scorm_pdf.read_bytes()).hexdigest()
        assert hash_before == hash_after

def test_80_scorm_pdf_watermark_zero_disk(test_token):
    """80. Watermarked SCORM PDF generation writes zero files to output/."""
    output_dir = Path(__file__).resolve().parent.parent / "output"
    files_before = {f.name for f in output_dir.glob("*") if f.name != ".gitkeep"}

    fresh_client = TestClient(app)
    response = fresh_client.post(
        "/scorm/neema-scorm-1.2/pdf",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200

    files_after = {f.name for f in output_dir.glob("*") if f.name != ".gitkeep"}
    assert files_before == files_after == set()

def test_81_all_roles_can_access_scorm_pdf():
    """81. ADMIN, TEACHER, and STUDENT roles can all watermark and retrieve SCORM PDF."""
    for user, pwd in [("admin1", "adminpass"), ("teacher1", "teacherpass"), ("student1", "studentpass")]:
        login_client = TestClient(app)
        login_resp = login_client.post("/token", data={"username": user, "password": pwd})
        token = login_resp.json()["access_token"]

        wm_client = TestClient(app)
        res = wm_client.post(
            "/scorm/neema-scorm-1.2/pdf",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/pdf"

# ==========================================
# DYNAMIC IST TIMESTAMP & INTERCEPTION TESTS (82 - 88)
# ==========================================

def test_82_watermark_contains_ist_timezone(test_token):
    """82. Generated watermark contains IST timestamp in Asia/Kolkata timezone, not UTC."""
    fresh_client = TestClient(app)
    response = fresh_client.post(
        "/scorm/neema-scorm-1.2/pdf",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert response.status_code == 200
    doc = pymupdf.open(stream=io.BytesIO(response.content), filetype="pdf")
    first_page_text = doc[0].get_text()
    assert "IST" in first_page_text
    assert "UTC" not in first_page_text
    doc.close()

def test_83_watermark_timestamp_is_dynamic(test_token):
    """83. Watermark timestamp is generated dynamically per request without hardcoding."""
    import time
    fresh_client = TestClient(app)
    res1 = fresh_client.post(
        "/scorm/neema-scorm-1.2/pdf",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert res1.status_code == 200
    doc1 = pymupdf.open(stream=io.BytesIO(res1.content), filetype="pdf")
    text1 = doc1[0].get_text()
    doc1.close()

    time.sleep(1.1)

    res2 = fresh_client.post(
        "/scorm/neema-scorm-1.2/pdf",
        headers={"Authorization": f"Bearer {test_token}"}
    )
    assert res2.status_code == 200
    doc2 = pymupdf.open(stream=io.BytesIO(res2.content), filetype="pdf")
    text2 = doc2[0].get_text()
    doc2.close()

    # The timestamp lines should differ by at least 1 second
    assert text1 != text2

def test_84_scorm_direct_pdf_route_intercepted_and_watermarked(test_token):
    """84. Accessing neema-book.pdf via SCORM sub-resource route returns watermarked PDF."""
    fresh_client = TestClient(app, cookies={"access_token": test_token})
    response = fresh_client.get("/scorm/neema-scorm-1.2/neema-book.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    
    doc = pymupdf.open(stream=io.BytesIO(response.content), filetype="pdf")
    assert doc.is_pdf
    page_text = doc[0].get_text()
    assert "CONFIDENTIAL" in page_text
    assert "admin1" in page_text
    assert "IST" in page_text
    doc.close()

def test_85_unauthenticated_direct_pdf_access_blocked():
    """85. Unauthenticated direct access to the SCORM PDF is rejected with HTTP 401."""
    fresh_client = TestClient(app)
    response = fresh_client.get("/scorm/neema-scorm-1.2/neema-book.pdf")
    assert response.status_code == 401
    assert "Authentication required" in response.json()["detail"]

def test_86_watermark_is_real_pdf_vector_text(test_token):
    """86. Output PDF contains searchable/selectable text and not raster images."""
    fresh_client = TestClient(app)
    response = fresh_client.post(
        "/watermark",
        headers={"Authorization": f"Bearer {test_token}"},
        json={"pdf_filename": "100ques.pdf"}
    )
    assert response.status_code == 200
    doc = pymupdf.open(stream=io.BytesIO(response.content), filetype="pdf")
    for page in doc:
        text = page.get_text()
        assert len(text) > 0
        assert "CONFIDENTIAL" in text
        assert "USR-001" in text
        assert "IST" in text
    doc.close()








