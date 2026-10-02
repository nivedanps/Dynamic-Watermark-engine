/**
 * Dynamic Digital Watermarking Engine - Frontend Controller
 * Document & SCORM Selection, In-Memory JWT Authentication, and Zero-Disk Processing.
 */

(function () {
    'use strict';

    // API Configuration
    const API_BASE = '';

    // State maintained strictly in memory (never in localStorage or sessionStorage)
    let authToken = null;
    let currentUser = null;
    let availableDocuments = [];
    let selectedDocument = null;
    let currentPdfBlobUrl = null;
    let currentWatermarkedFilename = null;
    let currentScormUrl = null;

    // DOM Elements - Sections & Headers
    const loginSection = document.getElementById('login-section');
    const dashboardSection = document.getElementById('dashboard-section');
    const userSessionBar = document.getElementById('user-session-bar');
    const loginForm = document.getElementById('login-form');
    const usernameInput = document.getElementById('username-input');
    const passwordInput = document.getElementById('password-input');
    const loginSubmitBtn = document.getElementById('login-submit-btn');
    const loginAlert = document.getElementById('login-alert');
    const dashboardAlert = document.getElementById('dashboard-alert');
    const logoutBtn = document.getElementById('logout-btn');

    // Dashboard Identity Elements
    const navAvatar = document.getElementById('nav-avatar');
    const navUsername = document.getElementById('nav-username');
    const navRole = document.getElementById('nav-role');
    const identityUser = document.getElementById('identity-user');
    const identityId = document.getElementById('identity-id');
    const identityRole = document.getElementById('identity-role');
    const identitySchool = document.getElementById('identity-school');
    const watermarkPreviewText = document.getElementById('watermark-preview-text');

    // Document Listing Elements
    const documentsContainer = document.getElementById('documents-container');
    const refreshDocsBtn = document.getElementById('refresh-docs-btn');

    // Selected Document / Book Elements
    const selectedDocSection = document.getElementById('selected-doc-section');
    const selectedDocLabel = document.getElementById('selected-doc-label');
    const selectedDocIcon = document.getElementById('selected-doc-icon');
    const selectedDocName = document.getElementById('selected-doc-name');
    const selectedDocMeta = document.getElementById('selected-doc-meta');
    const openBookBtn = document.getElementById('open-book-btn');
    const applyWatermarkBtn = document.getElementById('apply-watermark-btn');
    const applyBtnText = document.getElementById('apply-btn-text');
    const downloadActionBtn = document.getElementById('download-action-btn');
    const scormPdfSubpanel = document.getElementById('scorm-pdf-subpanel');
    const scormPdfFilename = document.getElementById('scorm-pdf-filename');

    // Result Card Elements
    const resultCard = document.getElementById('result-card');
    const resultTitle = document.getElementById('result-title');
    const resultDocumentName = document.getElementById('result-document-name');
    const resultStatusTag = document.getElementById('result-status-tag');
    const viewPdfBtn = document.getElementById('view-pdf-btn');
    const viewBtnText = document.getElementById('view-btn-text');
    const downloadPdfBtn = document.getElementById('download-pdf-btn');
    const downloadBtnText = document.getElementById('download-btn-text');
    const pdfPreviewFrame = document.getElementById('pdf-preview-frame');
    const viewerWatermarkOverlay = document.getElementById('viewer-watermark-overlay');
    const viewerWatermarkGrid = document.getElementById('viewer-watermark-grid');

    // Initialize Event Listeners
    function init() {
        // Quick account fill buttons
        document.querySelectorAll('.chip-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                usernameInput.value = btn.getAttribute('data-user') || '';
                passwordInput.value = btn.getAttribute('data-pass') || '';
                usernameInput.focus();
            });
        });

        // Form Submit & Logout
        loginForm.addEventListener('submit', handleLogin);
        logoutBtn.addEventListener('click', handleLogout);

        // Document list refresh
        if (refreshDocsBtn) {
            refreshDocsBtn.addEventListener('click', () => {
                fetchDocuments();
            });
        }

        // Action buttons
        if (openBookBtn) {
            openBookBtn.addEventListener('click', () => {
                if (selectedDocument && selectedDocument.type === 'scorm') {
                    handleOpenInteractiveScorm(selectedDocument);
                }
            });
        }

        if (applyWatermarkBtn) {
            applyWatermarkBtn.addEventListener('click', handleExecuteOpenPdf);
        }

        if (downloadActionBtn) {
            downloadActionBtn.addEventListener('click', () => {
                if (selectedDocument) {
                    handleDownloadWatermarkedPdf(selectedDocument);
                }
            });
        }

        // Result Card Actions
        if (viewPdfBtn) {
            viewPdfBtn.addEventListener('click', handleViewContent);
        }
        if (downloadPdfBtn) {
            downloadPdfBtn.addEventListener('click', () => {
                if (selectedDocument) {
                    handleDownloadWatermarkedPdf(selectedDocument);
                } else if (currentPdfBlobUrl && currentWatermarkedFilename) {
                    triggerBlobDownload(currentPdfBlobUrl, currentWatermarkedFilename);
                }
            });
        }
    }

    // Helper: Generate current Indian Standard Time (IST) string: YYYY-MM-DD HH:MM:SS IST
    function getFormattedIstTimestamp() {
        try {
            const now = new Date();
            const options = {
                timeZone: 'Asia/Kolkata',
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false
            };
            const formatter = new Intl.DateTimeFormat('en-CA', options);
            const parts = formatter.formatToParts(now);
            const pMap = {};
            parts.forEach(p => pMap[p.type] = p.value);
            return `${pMap.year}-${pMap.month}-${pMap.day} ${pMap.hour}:${pMap.minute}:${pMap.second} IST`;
        } catch (e) {
            return new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST';
        }
    }

    // Helper: Parse JWT payload safely in browser
    function parseJwt(token) {
        try {
            const base64Url = token.split('.')[1];
            const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
            const jsonPayload = decodeURIComponent(atob(base64).split('').map(function (c) {
                return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
            }).join(''));
            return JSON.parse(jsonPayload);
        } catch (e) {
            return null;
        }
    }

    // Helper: Format bytes to human-readable size
    function formatBytes(bytes) {
        if (!bytes || bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    // Escape HTML to prevent injection in filenames
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    // Alert helpers
    function showAlert(alertEl, message, type = 'error') {
        if (!alertEl) return;
        alertEl.className = `alert alert-${type}`;
        alertEl.textContent = message;
        alertEl.classList.remove('hidden');
    }

    function hideAlert(alertEl) {
        if (!alertEl) return;
        alertEl.classList.add('hidden');
        alertEl.textContent = '';
    }

    // Clean up created Blob URLs to prevent memory leaks
    function cleanupBlobUrl() {
        if (currentPdfBlobUrl) {
            URL.revokeObjectURL(currentPdfBlobUrl);
            currentPdfBlobUrl = null;
        }
        currentScormUrl = null;
        if (pdfPreviewFrame) {
            pdfPreviewFrame.src = 'about:blank';
        }
        if (viewerWatermarkOverlay) {
            viewerWatermarkOverlay.classList.add('hidden');
        }
    }

    // Handle Login Flow
    async function handleLogin(e) {
        e.preventDefault();
        hideAlert(loginAlert);

        const username = usernameInput.value.trim();
        const password = passwordInput.value;

        if (!username || !password) {
            showAlert(loginAlert, 'Please enter both username and password.');
            return;
        }

        const btnText = loginSubmitBtn.querySelector('.btn-text');
        const spinner = loginSubmitBtn.querySelector('.btn-spinner');
        loginSubmitBtn.disabled = true;
        if (btnText) btnText.textContent = 'Authenticating...';
        if (spinner) spinner.classList.remove('hidden');

        try {
            const response = await fetch(`${API_BASE}/token`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: new URLSearchParams({
                    username: username,
                    password: password
                })
            });

            if (!response.ok) {
                if (response.status === 401) {
                    throw new Error('Invalid username or password.');
                }
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Authentication failed. Please try again.');
            }

            const data = await response.json();
            authToken = data.access_token;

            // Extract claims from JWT
            const claims = parseJwt(authToken);
            currentUser = {
                username: (claims && claims.sub) ? claims.sub : username,
                user_id: (claims && claims.user_id) ? claims.user_id : 'USR-001',
                role: (claims && claims.role) ? claims.role : 'STUDENT',
                school_name: 'Excelsoft Academy'
            };

            // Switch to Dashboard and load available documents
            showDashboard();
            await fetchDocuments();

        } catch (err) {
            showAlert(loginAlert, err.message);
        } finally {
            loginSubmitBtn.disabled = false;
            if (btnText) btnText.textContent = 'Sign In';
            if (spinner) spinner.classList.add('hidden');
        }
    }

    // Switch view to Dashboard
    function showDashboard() {
        loginSection.classList.add('hidden');
        dashboardSection.classList.remove('hidden');
        userSessionBar.classList.remove('hidden');

        // Populate User Identity Details
        if (currentUser) {
            navAvatar.textContent = currentUser.username.charAt(0).toUpperCase();
            navUsername.textContent = currentUser.username;
            navRole.textContent = currentUser.role;

            identityUser.textContent = currentUser.username;
            identityId.textContent = currentUser.user_id;
            identityRole.textContent = currentUser.role;
            if (identitySchool) identitySchool.textContent = currentUser.school_name;

            const istNow = getFormattedIstTimestamp();
            if (watermarkPreviewText) {
                watermarkPreviewText.textContent = `CONFIDENTIAL — LICENSED TO: ${currentUser.username}\nID: ${currentUser.user_id}\n${currentUser.school_name}\n${istNow}`;
            }
        }
    }

    // Handle Logout
    async function handleLogout() {
        cleanupBlobUrl();
        authToken = null;
        currentUser = null;
        selectedDocument = null;
        availableDocuments = [];
        currentWatermarkedFilename = null;

        try {
            await fetch(`${API_BASE}/logout`, { method: 'POST' });
        } catch (e) {
            // Ignore logout network error if already offline
        }

        // Reset UI
        loginForm.reset();
        hideAlert(loginAlert);
        hideAlert(dashboardAlert);
        if (resultCard) resultCard.classList.add('hidden');
        if (selectedDocSection) selectedDocSection.classList.add('hidden');
        if (documentsContainer) documentsContainer.innerHTML = '';

        dashboardSection.classList.add('hidden');
        userSessionBar.classList.add('hidden');
        loginSection.classList.remove('hidden');
    }

    function handleSessionExpired() {
        handleLogout();
        showAlert(loginAlert, 'Session expired. Please log in again.', 'warning');
    }

    // Fetch and display available documents from backend
    async function fetchDocuments() {
        hideAlert(dashboardAlert);
        if (!authToken) {
            handleSessionExpired();
            return;
        }

        // Show loading state
        documentsContainer.innerHTML = `
            <div class="state-box">
                <span class="state-spinner"></span>
                <span>Loading available documents...</span>
            </div>
        `;

        try {
            const response = await fetch(`${API_BASE}/documents`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            });

            if (!response.ok) {
                if (response.status === 401) {
                    handleSessionExpired();
                    return;
                }
                if (response.status === 403) {
                    throw new Error('You are not authorized to view available documents.');
                }
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Unable to load available documents.');
            }

            const data = await response.json();
            const docs = data.documents || (Array.isArray(data) ? data : []);
            availableDocuments = docs;
            renderDocumentList(docs);

        } catch (err) {
            showAlert(dashboardAlert, err.message);
            documentsContainer.innerHTML = `
                <div class="state-box">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <line x1="12" y1="16" x2="12"/>
                        <line x1="12" y1="8" x2="12.01" y2="8"/>
                    </svg>
                    <span>Unable to load available documents.</span>
                    <button type="button" id="retry-fetch-btn" class="btn btn-secondary btn-sm" style="margin-top: 8px;">
                        Retry
                    </button>
                </div>
            `;
            const retryBtn = document.getElementById('retry-fetch-btn');
            if (retryBtn) {
                retryBtn.addEventListener('click', fetchDocuments);
            }
        }
    }

    // Render documents list
    function renderDocumentList(docs) {
        if (!docs || docs.length === 0) {
            documentsContainer.innerHTML = `
                <div class="state-box">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                        <polyline points="14 2 14 8 20 8"/>
                    </svg>
                    <span>No documents or books are currently available.</span>
                </div>
            `;
            if (selectedDocSection) selectedDocSection.classList.add('hidden');
            selectedDocument = null;
            return;
        }

        documentsContainer.innerHTML = '';
        docs.forEach(doc => {
            const isScorm = doc.type === 'scorm';
            const card = document.createElement('div');
            card.className = 'doc-card';
            card.id = `doc-card-${doc.id.replace(/[^a-zA-Z0-9_-]/g, '_')}`;

            const isSelected = selectedDocument && selectedDocument.id === doc.id;
            if (isSelected) {
                card.classList.add('selected');
            }

            const iconHtml = isScorm
                ? `<div class="doc-icon scorm-icon" style="font-size: 1.3rem;">📚</div>`
                : `<div class="doc-icon" style="font-size: 1.3rem;">📄</div>`;

            const metaHtml = isScorm
                ? `<span class="doc-badge badge-scorm">SCORM 1.2 Package</span>`
                : `<span class="doc-badge">PDF</span> <span>&bull;</span> <span>${formatBytes(doc.size)}</span>`;

            const actionBtnLabel = isScorm ? 'Open Book' : (isSelected ? 'Selected' : 'Select');

            card.innerHTML = `
                <div class="doc-info">
                    ${iconHtml}
                    <div class="doc-meta">
                        <span class="doc-name">${escapeHtml(doc.name || doc.filename)}</span>
                        <div class="doc-details">
                            ${metaHtml}
                        </div>
                    </div>
                </div>
                <button type="button" class="btn btn-secondary btn-sm btn-select-doc">
                    ${actionBtnLabel}
                </button>
            `;

            // Click card to select
            card.addEventListener('click', () => {
                selectDocument(doc);
                if (isScorm && doc.has_pdf) {
                    handleApplyScormPdfWatermark(doc);
                } else if (isScorm) {
                    handleOpenInteractiveScorm(doc);
                }
            });

            documentsContainer.appendChild(card);
        });

        // Re-select active document if still available
        if (selectedDocument) {
            const stillExists = docs.some(d => d.id === selectedDocument.id);
            if (!stillExists) {
                deselectDocument();
            }
        }
    }

    // Select a document / book
    function selectDocument(doc) {
        selectedDocument = doc;
        const isScorm = doc.type === 'scorm';

        // Update active selection UI on cards
        document.querySelectorAll('.doc-card').forEach(card => {
            card.classList.remove('selected');
            const btn = card.querySelector('.btn-select-doc');
            if (btn && !btn.textContent.includes('Open Book')) {
                btn.textContent = 'Select';
            }
        });

        const activeCard = document.getElementById(`doc-card-${doc.id.replace(/[^a-zA-Z0-9_-]/g, '_')}`);
        if (activeCard) {
            activeCard.classList.add('selected');
            const btn = activeCard.querySelector('.btn-select-doc');
            if (btn && !isScorm) {
                btn.textContent = 'Selected';
            }
        }

        // Configure Selected Box
        if (selectedDocSection) {
            if (isScorm) {
                selectedDocLabel.textContent = 'Selected Book';
                selectedDocIcon.textContent = '📚';
                selectedDocName.textContent = doc.name || doc.id;
                selectedDocMeta.className = 'doc-badge badge-scorm';
                selectedDocMeta.textContent = 'SCORM 1.2 Package';

                // Show Open Book button for SCORM
                if (openBookBtn) {
                    openBookBtn.classList.remove('hidden');
                }

                if (doc.has_pdf && doc.pdf_filename) {
                    if (scormPdfSubpanel) scormPdfSubpanel.classList.remove('hidden');
                    if (scormPdfFilename) scormPdfFilename.textContent = doc.pdf_filename;
                    if (applyWatermarkBtn) applyWatermarkBtn.classList.remove('hidden');
                    if (applyBtnText) applyBtnText.textContent = 'Open PDF';
                    if (downloadActionBtn) downloadActionBtn.classList.remove('hidden');
                } else {
                    if (scormPdfSubpanel) scormPdfSubpanel.classList.add('hidden');
                    if (applyWatermarkBtn) applyWatermarkBtn.classList.add('hidden');
                    if (downloadActionBtn) downloadActionBtn.classList.add('hidden');
                }
            } else {
                if (openBookBtn) openBookBtn.classList.add('hidden');
                if (scormPdfSubpanel) scormPdfSubpanel.classList.add('hidden');
                selectedDocLabel.textContent = 'Selected Document';
                selectedDocIcon.textContent = '📄';
                selectedDocName.textContent = doc.filename || doc.name;
                selectedDocMeta.className = 'doc-badge';
                selectedDocMeta.textContent = `PDF • ${formatBytes(doc.size)}`;

                if (applyWatermarkBtn) applyWatermarkBtn.classList.remove('hidden');
                if (applyBtnText) applyBtnText.textContent = 'Open PDF';
                if (downloadActionBtn) downloadActionBtn.classList.remove('hidden');
            }
            selectedDocSection.classList.remove('hidden');
        }

        // Hide result card if switching documents
        if (!isScorm && resultCard) {
            resultCard.classList.add('hidden');
        }
    }

    function deselectDocument() {
        selectedDocument = null;
        if (selectedDocSection) {
            selectedDocSection.classList.add('hidden');
        }
    }

    // Trigger action to open/view watermarked PDF
    function handleExecuteOpenPdf() {
        if (!selectedDocument) {
            showAlert(dashboardAlert, 'Please select a document or book first.');
            return;
        }

        if (selectedDocument.type === 'scorm') {
            if (selectedDocument.has_pdf) {
                handleApplyScormPdfWatermark(selectedDocument);
            } else {
                handleOpenInteractiveScorm(selectedDocument);
            }
        } else {
            handleApplyWatermark();
        }
    }

    // Handle opening interactive SCORM viewer (Reader)
    function handleOpenInteractiveScorm(doc) {
        hideAlert(dashboardAlert);
        if (!authToken) {
            handleSessionExpired();
            return;
        }

        cleanupBlobUrl();

        const entryPoint = doc.entry_point || 'index.html';
        const scormUrl = `${API_BASE}/scorm/${encodeURIComponent(doc.id)}/${entryPoint}`;
        currentScormUrl = scormUrl;

        // Configure result card for SCORM viewer
        if (resultTitle) resultTitle.textContent = doc.name || "What's Neema Eating Today?";
        if (resultDocumentName) resultDocumentName.textContent = doc.id;
        if (resultStatusTag) resultStatusTag.textContent = 'SCORM 1.2 Content • Interactive Reader';
        if (viewBtnText) viewBtnText.textContent = 'Open in New Window';
        if (downloadPdfBtn) downloadPdfBtn.classList.remove('hidden');
        if (downloadBtnText) downloadBtnText.textContent = 'Download Watermarked PDF';

        if (pdfPreviewFrame) {
            pdfPreviewFrame.src = scormUrl;
        }

        if (resultCard) {
            resultCard.classList.remove('hidden');
            resultCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

        showAlert(dashboardAlert, `✓ Launched interactive book: ${doc.name || doc.id}`, 'success');
    }

    // Handle Watermark request for PDF located inside SCORM package
    async function handleApplyScormPdfWatermark(doc) {
        hideAlert(dashboardAlert);

        if (!authToken) {
            handleSessionExpired();
            return;
        }

        const spinner = applyWatermarkBtn ? applyWatermarkBtn.querySelector('.btn-spinner') : null;
        if (applyWatermarkBtn) applyWatermarkBtn.disabled = true;
        if (applyBtnText) applyBtnText.textContent = 'Watermarking PDF...';
        if (spinner) spinner.classList.remove('hidden');

        try {
            const response = await fetch(`${API_BASE}/scorm/${encodeURIComponent(doc.id)}/pdf`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            });

            if (!response.ok) {
                if (response.status === 401) {
                    handleSessionExpired();
                    return;
                }
                if (response.status === 403) {
                    throw new Error('You are not authorized to access this SCORM document.');
                }
                if (response.status === 404) {
                    throw new Error('The PDF document inside the SCORM package was not found.');
                }
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Unable to generate the watermarked PDF.');
            }

            // Receive pure watermarked PDF bytes directly in memory as a Blob
            const blob = await response.blob();

            cleanupBlobUrl();

            currentPdfBlobUrl = URL.createObjectURL(blob);
            const rawPdfName = doc.pdf_filename || `${doc.id}.pdf`;
            currentWatermarkedFilename = `watermarked_${rawPdfName}`;

            // Configure Result Section for Watermarked PDF
            if (resultTitle) resultTitle.textContent = 'Watermark Applied to SCORM PDF';
            if (resultDocumentName) resultDocumentName.textContent = rawPdfName;
            if (resultStatusTag) resultStatusTag.textContent = 'Discovered inside SCORM • Dynamic IST Watermark • In-Memory Processing';
            if (viewBtnText) viewBtnText.textContent = 'View PDF';
            if (downloadPdfBtn) downloadPdfBtn.classList.remove('hidden');
            if (downloadBtnText) downloadBtnText.textContent = 'Download Watermarked PDF';

            if (pdfPreviewFrame) {
                pdfPreviewFrame.src = currentPdfBlobUrl;
            }
            if (resultCard) {
                resultCard.classList.remove('hidden');
                resultCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }

            showAlert(dashboardAlert, `✓ Watermarked PDF generated successfully with dynamic IST timestamp for ${rawPdfName}`, 'success');

        } catch (err) {
            showAlert(dashboardAlert, err.message, 'error');
        } finally {
            if (applyWatermarkBtn) applyWatermarkBtn.disabled = false;
            if (applyBtnText) applyBtnText.textContent = 'Open PDF';
            if (spinner) spinner.classList.add('hidden');
        }
    }

    // Handle Watermark request for selected standalone PDF
    async function handleApplyWatermark() {
        hideAlert(dashboardAlert);

        if (!selectedDocument || selectedDocument.type !== 'pdf') {
            showAlert(dashboardAlert, 'Please select a PDF document first.');
            return;
        }

        if (!authToken) {
            handleSessionExpired();
            return;
        }

        const spinner = applyWatermarkBtn ? applyWatermarkBtn.querySelector('.btn-spinner') : null;
        if (applyWatermarkBtn) applyWatermarkBtn.disabled = true;
        if (applyBtnText) applyBtnText.textContent = 'Applying watermark...';
        if (spinner) spinner.classList.remove('hidden');

        try {
            const filename = selectedDocument.filename || selectedDocument.id;
            const response = await fetch(`${API_BASE}/watermark`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify({
                    pdf_filename: filename
                })
            });

            if (!response.ok) {
                if (response.status === 401) {
                    handleSessionExpired();
                    return;
                }
                if (response.status === 403) {
                    throw new Error('You are not authorized to watermark this document.');
                }
                if (response.status === 404) {
                    throw new Error('The selected document was not found.');
                }
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Unable to generate the watermarked PDF.');
            }

            // Receive pure watermarked PDF bytes directly in memory as a Blob
            const blob = await response.blob();

            cleanupBlobUrl();

            currentPdfBlobUrl = URL.createObjectURL(blob);
            currentWatermarkedFilename = `watermarked_${filename}`;

            // Configure Result Section for PDF
            if (resultTitle) resultTitle.textContent = 'Watermark Applied Successfully';
            if (resultDocumentName) resultDocumentName.textContent = filename;
            if (resultStatusTag) resultStatusTag.textContent = 'Processed in RAM • Dynamic IST Watermark • Zero Server Storage';
            if (viewBtnText) viewBtnText.textContent = 'View PDF';
            if (downloadPdfBtn) downloadPdfBtn.classList.remove('hidden');
            if (downloadBtnText) downloadBtnText.textContent = 'Download Watermarked PDF';

            if (pdfPreviewFrame) {
                pdfPreviewFrame.src = currentPdfBlobUrl;
            }
            if (resultCard) {
                resultCard.classList.remove('hidden');
                resultCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }

            showAlert(dashboardAlert, `✓ Watermark applied successfully with dynamic IST timestamp for ${filename}`, 'success');

        } catch (err) {
            showAlert(dashboardAlert, err.message, 'error');
        } finally {
            if (applyWatermarkBtn) applyWatermarkBtn.disabled = false;
            if (applyBtnText) applyBtnText.textContent = 'Open PDF';
            if (spinner) spinner.classList.add('hidden');
        }
    }

    // Helper: Trigger browser download for a Blob
    function triggerBlobDownload(blobUrl, filename) {
        const anchor = document.createElement('a');
        anchor.href = blobUrl;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
    }

    // Handle dynamically downloading freshly watermarked PDF from the backend endpoint
    async function handleDownloadWatermarkedPdf(doc) {
        hideAlert(dashboardAlert);

        if (!doc) {
            showAlert(dashboardAlert, 'Please select a document or book first.');
            return;
        }

        if (!authToken) {
            handleSessionExpired();
            return;
        }

        const isScorm = doc.type === 'scorm';
        const rawFilename = isScorm ? (doc.pdf_filename || `${doc.id}.pdf`) : (doc.filename || doc.id);
        const downloadFilename = `watermarked_${rawFilename}`;

        const origBtnText = downloadActionBtn ? downloadActionBtn.querySelector('span').textContent : '';
        if (downloadActionBtn) {
            downloadActionBtn.disabled = true;
            downloadActionBtn.querySelector('span').textContent = 'Downloading...';
        }

        try {
            let response;
            if (isScorm) {
                response = await fetch(`${API_BASE}/scorm/${encodeURIComponent(doc.id)}/pdf`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${authToken}`
                    }
                });
            } else {
                response = await fetch(`${API_BASE}/watermark`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${authToken}`
                    },
                    body: JSON.stringify({
                        pdf_filename: rawFilename
                    })
                });
            }

            if (!response.ok) {
                if (response.status === 401) {
                    handleSessionExpired();
                    return;
                }
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Unable to download watermarked PDF.');
            }

            const blob = await response.blob();
            const tempUrl = URL.createObjectURL(blob);
            triggerBlobDownload(tempUrl, downloadFilename);
            setTimeout(() => URL.revokeObjectURL(tempUrl), 60000);

            showAlert(dashboardAlert, `✓ Downloaded freshly watermarked PDF: ${downloadFilename}`, 'success');

        } catch (err) {
            showAlert(dashboardAlert, err.message, 'error');
        } finally {
            if (downloadActionBtn) {
                downloadActionBtn.disabled = false;
                downloadActionBtn.querySelector('span').textContent = origBtnText || 'Download Watermarked PDF';
            }
        }
    }

    // View PDF or SCORM in new browser window/tab
    function handleViewContent() {
        if (selectedDocument && selectedDocument.type === 'scorm' && currentScormUrl && (!currentPdfBlobUrl || pdfPreviewFrame.src.includes('/scorm/'))) {
            window.open(currentScormUrl, '_blank');
        } else if (currentPdfBlobUrl) {
            window.open(currentPdfBlobUrl, '_blank');
        } else {
            showAlert(dashboardAlert, 'No content is currently available to view.');
        }
    }

    // Initialize application
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
