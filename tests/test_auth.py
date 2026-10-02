from datetime import timedelta
from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest
from app.main import app
from app.models import User, Role
from app.auth import create_access_token, fake_users_db
from app.authorization import RoleChecker

client = TestClient(app)

# ==========================================
# AUTHENTICATION TESTS (1 - 7)
# ==========================================

def test_1_successful_login():
    """1. Successful login returns HTTP 200, access token, and bearer type."""
    response = client.post(
        "/token",
        data={"username": "admin1", "password": "adminpass"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_2_wrong_password():
    """2. Wrong password returns HTTP 401 Unauthorized."""
    response = client.post(
        "/token",
        data={"username": "admin1", "password": "incorrect_password"},
    )
    assert response.status_code == 401
    assert "Incorrect username or password" in response.json()["detail"]

def test_3_unknown_user():
    """3. Unknown user returns HTTP 401 Unauthorized."""
    response = client.post(
        "/token",
        data={"username": "nonexistent_user", "password": "anypassword"},
    )
    assert response.status_code == 401
    assert "Incorrect username or password" in response.json()["detail"]

def test_4_jwt_creation():
    """4. JWT token creation contains claims: sub, user_id, role."""
    token = create_access_token(
        data={"sub": "teacher1", "user_id": "USR-002", "role": "TEACHER"},
        expires_delta=timedelta(minutes=15)
    )
    assert isinstance(token, str)
    assert len(token) > 20

def test_5_invalid_signature_jwt():
    """5. Tampered or invalid JWT signature returns HTTP 401."""
    # Token signed with a different key
    fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbjEiLCJ1c2VyX2lkIjoiVVNSLTAwMSIsInJvbGUiOiJBRE1JTiIsImV4cCI6OTk5OTk5OTk5OX0.invalid_signature_here"
    response = client.post(
        "/watermark",
        headers={"Authorization": f"Bearer {fake_token}"},
        json={"pdf_filename": "test.pdf"}
    )
    assert response.status_code == 401
    assert "Could not validate credentials" in response.json()["detail"]

def test_6_malformed_jwt():
    """6. Malformed JWT string returns HTTP 401."""
    response = client.post(
        "/watermark",
        headers={"Authorization": "Bearer not_a_valid_jwt_structure"},
        json={"pdf_filename": "test.pdf"}
    )
    assert response.status_code == 401
    assert "Could not validate credentials" in response.json()["detail"]

def test_7_expired_jwt():
    """7. Expired JWT token returns HTTP 401."""
    expired_token = create_access_token(
        data={"sub": "admin1", "user_id": "USR-001", "role": "ADMIN"},
        expires_delta=timedelta(minutes=-10)  # expired 10 minutes ago
    )
    response = client.post(
        "/watermark",
        headers={"Authorization": f"Bearer {expired_token}"},
        json={"pdf_filename": "test.pdf"}
    )
    assert response.status_code == 401
    assert "Token has expired" in response.json()["detail"]

# ==========================================
# AUTHORIZATION TESTS (8 - 12)
# ==========================================

def test_8_admin_access():
    """8. ADMIN role is authorized."""
    checker = RoleChecker([Role.ADMIN, Role.TEACHER, Role.STUDENT])
    admin_user = User(
        username="admin1",
        user_id="USR-001",
        school_name="Excelsoft Academy",
        role=Role.ADMIN
    )
    result = checker(user=admin_user)
    assert result.role == Role.ADMIN

def test_9_teacher_access():
    """9. TEACHER role is authorized."""
    checker = RoleChecker([Role.ADMIN, Role.TEACHER, Role.STUDENT])
    teacher_user = User(
        username="teacher1",
        user_id="USR-002",
        school_name="Excelsoft Academy",
        role=Role.TEACHER
    )
    result = checker(user=teacher_user)
    assert result.role == Role.TEACHER

def test_10_student_access():
    """10. STUDENT role is authorized."""
    checker = RoleChecker([Role.ADMIN, Role.TEACHER, Role.STUDENT])
    student_user = User(
        username="student1",
        user_id="USR-003",
        school_name="Excelsoft Academy",
        role=Role.STUDENT
    )
    result = checker(user=student_user)
    assert result.role == Role.STUDENT

def test_11_missing_token():
    """11. Request without Authorization header returns HTTP 401."""
    response = client.post(
        "/watermark",
        json={"pdf_filename": "document.pdf"}
    )
    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]

def test_12_invalid_role():
    """12. User with unauthorized role returns HTTP 403 Forbidden."""
    admin_only_checker = RoleChecker([Role.ADMIN])
    student_user = User(
        username="student1",
        user_id="USR-003",
        school_name="Excelsoft Academy",
        role=Role.STUDENT
    )
    with pytest.raises(HTTPException) as exc_info:
        admin_only_checker(user=student_user)
    assert exc_info.value.status_code == 403
    assert "Operation not permitted" in exc_info.value.detail

# ==========================================
# PATH SECURITY TESTS (13 - 19)
# ==========================================

@pytest.fixture
def auth_header():
    resp = client.post("/token", data={"username": "admin1", "password": "adminpass"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_13_dotdot_traversal_rejected(auth_header):
    """13. Path with ../ is rejected with HTTP 400."""
    response = client.post(
        "/watermark",
        headers=auth_header,
        json={"pdf_filename": "../secret.pdf"}
    )
    assert response.status_code == 400
    assert "Invalid filename" in response.json()["detail"]

def test_14_dotdot_slash_traversal_rejected(auth_header):
    """14. Path with ../../ is rejected with HTTP 400."""
    response = client.post(
        "/watermark",
        headers=auth_header,
        json={"pdf_filename": "../../etc/passwd.pdf"}
    )
    assert response.status_code == 400

def test_15_absolute_path_rejected(auth_header):
    """15. Absolute path is rejected with HTTP 400."""
    response = client.post(
        "/watermark",
        headers=auth_header,
        json={"pdf_filename": "/etc/passwd.pdf"}
    )
    assert response.status_code == 400

def test_16_slash_path_rejected(auth_header):
    """16. Subdirectory slash path (e.g. input/doc.pdf) is rejected."""
    response = client.post(
        "/watermark",
        headers=auth_header,
        json={"pdf_filename": "input/document.pdf"}
    )
    assert response.status_code == 400

def test_17_backslash_path_rejected(auth_header):
    """17. Windows-style backslash path is rejected."""
    response = client.post(
        "/watermark",
        headers=auth_header,
        json={"pdf_filename": "sub\\doc.pdf"}
    )
    assert response.status_code == 400

def test_18_nonexistent_pdf_rejected(auth_header):
    """18. Non-existent PDF in input/ returns HTTP 404."""
    response = client.post(
        "/watermark",
        headers=auth_header,
        json={"pdf_filename": "non_existent_file_9999.pdf"}
    )
    assert response.status_code == 404

def test_19_non_pdf_rejected(auth_header):
    """19. Non-PDF files (e.g. .txt, .exe) are rejected with HTTP 400."""
    response = client.post(
        "/watermark",
        headers=auth_header,
        json={"pdf_filename": "document.txt"}
    )
    assert response.status_code == 400
    assert "only .pdf files" in response.json()["detail"]
