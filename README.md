# Dynamic Digital Watermarking Engine - POC & Web Application

A production-grade, security-focused Python proof-of-concept and web application for dynamic digital PDF watermarking.

---

## 1. Project Purpose & Highlights
When authenticated educators, students, or administrators access educational documents, this application embeds a dynamic identity watermark (`Confidential - Licensed to: [USERNAME] (ID: [USER_ID]) | [SCHOOL] | [UTC_TIMESTAMP]`) across every page of the document in real time.

Key design guarantees:
- **Zero-Disk In-Memory Processing**: PDF byte streams are processed exclusively in RAM (`io.BytesIO`).
- **Source Document Immutability**: Original PDF files are read-only and never modified.
- **Zero Ephemeral Storage**: Watermarked PDFs are returned directly via HTTP responses and never stored on the server disk (`output/` remains empty).
- **Interactive Web Interface**: Complete HTML5 / CSS3 / Vanilla JS frontend served directly from FastAPI (`GET /`).
- **Framework Independence**: The core engine in `app/watermark.py` is fully decoupled from FastAPI, enabling future direct reimplementation as a C# .NET class library (`WatermarkEngine.dll`).

---

## 2. Architecture & Endpoints
```
[Browser Web Application / Swagger UI]
         │
         │  1. POST /token (OAuth2 form: username, password)
         ▼
[Authentication: pwdlib / Argon2] ──► Issues signed HS256 JWT Token
         │
         ├──► 2a. GET /documents (Bearer JWT)
         │        └── Scans input/ -> Returns safe list of available PDFs
         │
         └──► 2b. POST /watermark (JSON: {"pdf_filename": "..."} + Bearer JWT)
                  └── Reads input/ bytes into RAM -> In-Memory PyMuPDF -> In-Memory Blob Response
```

---

## 3. Project Structure
```
dynamic-watermark-poc/
├── app/
│   ├── __init__.py          # Application package initialization
│   ├── main.py              # FastAPI app, static mounting, /token, /documents, /watermark, /watermark/upload
│   ├── auth.py              # Argon2 password verification, JWT token issuance & claims
│   ├── authorization.py     # Role-Based Access Control (RBAC) dependency logic
│   ├── watermark.py         # Framework-independent core watermark engine (PyMuPDF)
│   ├── models.py            # Pydantic data schemas (Token, User, DocumentInfo, etc.)
│   └── config.py            # Environment-aware application configuration
├── static/
│   ├── index.html           # Modern glassmorphism web UI with document selection
│   ├── style.css            # Responsive dark-mode styling
│   └── app.js               # Frontend controller, in-memory token, document selection, blob view/download
├── input/                   # Place real PDF documents here (e.g. 100ques.pdf)
├── output/                  # Remains empty (never written to by server)
├── tests/
│   ├── __init__.py
│   ├── test_auth.py         # Auth, Authorization, and Path Security unit tests
│   └── test_watermark.py    # Watermark engine, GET /documents, upload endpoint & integration tests
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 4. Installation & Virtual Environment Setup
Ensure Python 3.14+ (or Python 3.11+) is installed.

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Upgrade pip and install dependencies
python -m pip install -r requirements.txt
```

---

## 5. Running the Application

### Start the Server
```bash
python -m uvicorn app.main:app --reload
```

### Accessing the Interfaces
- **Web Application**: **`http://127.0.0.1:8000/`**
- **Swagger API Docs**: **`http://127.0.0.1:8000/docs`**

---

## 6. Test Credentials (In-Memory Mock Users)
Passwords are stored exclusively as pre-computed **Argon2id** hashes in `app/auth.py`.

| Username | Password | Role | User ID | School |
| :--- | :--- | :--- | :--- | :--- |
| `admin1` | `adminpass` | `ADMIN` | `USR-001` | `Excelsoft Academy` |
| `teacher1` | `teacherpass` | `TEACHER` | `USR-002` | `Excelsoft Academy` |
| `student1` | `studentpass` | `STUDENT` | `USR-003` | `Excelsoft Academy` |

---

## 7. Web Application Features
1. **Secure Login**: Submits `POST /token` via OAuth2 password flow. The returned JWT is held strictly in JavaScript memory (never saved to `localStorage` or `sessionStorage`).
2. **Identity Dashboard**: Displays authenticated username, role badge, user ID, organization name, and live watermark string preview.
3. **Multi-Format Document Library**: Automatically discovers both server PDF documents and SCORM 1.2 interactive packages via `GET /documents`.
4. **PDF Watermarking Workflow**: Selecting a PDF enables **[ Apply Watermark ]**, generating a large, full-page diagonal watermark in memory and offering inline viewing and downloading.
5. **SCORM Book Launch Workflow**: Selecting a SCORM book displays title/organization parsed from `imsmanifest.xml` and launches the package safely via `/scorm/{package_id}/{file_path}`.
6. **Zero Server Storage**: Output directory remains untouched; original PDFs and SCORM assets remain read-only.
7. **Session Expiry & RBAC**: Automatically handles 401/403 responses and provides single-click logout.

---

## 8. API Endpoints

### 1. `GET /`
Serves the web application (`static/index.html`).

### 2. `POST /token`
- Content-Type: `application/x-www-form-urlencoded`
- Fields: `username`, `password`
- Returns: `{"access_token": "...", "token_type": "bearer"}`

### 3. `GET /documents`
- Headers: `Authorization: Bearer <JWT>`
- Returns: List of available PDFs and SCORM packages with metadata (parsed titles, entry points, sizes).

### 4. `GET /scorm/{package_id}/{file_path:path}`
- Headers: `Authorization: Bearer <JWT>` or `?token=<JWT>` query parameter.
- Safely serves authenticated SCORM packages and sub-resources without path traversal.

### 5. `POST /watermark`
- Content-Type: `application/json`
- Headers: `Authorization: Bearer <JWT>`
- Body: `{"pdf_filename": "100ques.pdf"}`
- Reads file from `input/` folder into RAM, validates path bounds, applies in-memory watermark, and streams `application/pdf`.

### 6. `POST /watermark/upload`
- Content-Type: `multipart/form-data`
- Headers: `Authorization: Bearer <JWT>`
- Form field: `file` (PDF file)
- Enforces size limit, validates `%PDF` header, applies in-memory watermark, and returns `application/pdf`.

---

## 9. Configuration & Environment Variables
Configuration is defined in `app/config.py`:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `JWT_SECRET_KEY` | *(Safe Development Default)* | Secret key for signing JWT tokens. |
| `JWT_ALGORITHM` | `HS256` | Cryptographic algorithm for JWT signatures. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | JWT token lifetime in minutes. |
| `INPUT_DIR` | `input/` | Directory path where original PDFs and SCORM packages are stored. |
| `STATIC_DIR` | `static/` | Directory path for frontend static assets. |
| `WATERMARK_OPACITY` | `0.20` | Default watermark opacity (0.0 to 1.0). |
| `MAX_UPLOAD_SIZE_MB` | `20` | Maximum upload size in megabytes. |

---

## 10. Security Controls & Zero-Disk Processing
1. **Zero Disk Footprint**: `output/` remains permanently empty. Output exists only as transient RAM streams.
2. **Document Immutability**: Files in `input/` are opened read-only and never modified.
3. **Path Traversal Protection**: Rejects `..`, `/`, `\`, absolute paths, and subdirectories on both `/watermark` and `/scorm/...`.
4. **Header Magic Byte Check**: Validates `%PDF` header bytes before parsing.
5. **Credential Privacy in Logs**: Passwords, tokens, and Authorization headers are strictly omitted from audit logs.
6. **Structured Audit Logging**: Emits timestamp, username, user ID, role, document/package, action, and status.

---

## 11. Automated Test Suite
Run all automated tests:
```bash
python -m pytest -q
```
**Current Result: 59 passed**

### Test Coverage Summary:
- **Authentication (Tests 1-7)**: Successful login, incorrect password, unknown user, JWT structure, invalid signature, malformed token, expired token.
- **Authorization (Tests 8-12)**: ADMIN/TEACHER/STUDENT access, missing token, unpermitted role rejection.
- **Path Security (Tests 13-19)**: `../`, `../../`, absolute paths, subdirectories, backslashes, nonexistent files, non-PDF files.
- **Watermark Engine (Tests 20-27)**: In-memory byte streaming, valid PDF structure, byte type guarantees, page count preservation, watermark on every page, byte immutability, portrait/landscape scaling, opacity variations.
- **Endpoints & Audit (Tests 28-34)**: Authenticated flow, unauthenticated blocking, `application/pdf` headers, zero-disk verification on `output/`, audit log emission, credential omission in logs.
- **Upload & Document Listing (Tests 35-49)**: `GET /` HTML delivery, `POST /watermark/upload` checks, `input/100ques.pdf` SHA-256 hash immutability, `GET /documents` authentication check, list response validation, `.gitkeep` exclusion, non-SCORM subdirectory exclusion, non-PDF exclusion, and server filesystem path concealment.
- **Large Diagonal Watermark Suite (Tests 50-53)**: Multi-line dynamic formatting, portrait and landscape diagonal scaling, custom opacity adherence.
- **SCORM Serving & Security Suite (Tests 54-59)**: SCORM discovery and classification from `imsmanifest.xml`, unauthenticated SCORM blocking (401), entry point serving with header, asset serving with query token, path traversal rejection (400), and missing file handling (404).



---

## 12. Future Porting to C# / .NET
The core watermark engine in `app/watermark.py` accepts and returns raw `bytes`, maintaining strict separation from web framework abstractions.

This design enables direct 1-to-1 porting to a C# .NET class library:
- Target Library: **`WatermarkEngine.dll`**
- Core Signature in C#:
  ```csharp
  public static byte[] ApplyWatermark(byte[] pdfBytes, string watermarkText, float opacity = 0.20f)
  ```

