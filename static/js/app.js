// Global state
let currentPdfId = null;
let detectedSections = [];
let createdSets = [];

// DOM Elements
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const uploadProgress = document.getElementById('upload-progress');
const progressFill = document.getElementById('progress-fill');
const alertContainer = document.getElementById('alert-container');
const pdfInfoSection = document.getElementById('pdf-info-section');
const sectionsSection = document.getElementById('sections-section');
const setsSection = document.getElementById('sets-section');
const autoDetectBtn = document.getElementById('auto-detect-btn');
const createSetsBtn = document.getElementById('create-sets-btn');
const processAllBtn = document.getElementById('process-all-btn');
const refreshPatientsBtn = document.getElementById('refresh-patients-btn');

// Utility Functions
function showAlert(message, type = 'info') {
    const alertClass = `alert-${type}`;
    const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
    
    const alert = document.createElement('div');
    alert.className = `alert ${alertClass}`;
    alert.innerHTML = `<span>${icon}</span><span>${message}</span>`;
    
    alertContainer.innerHTML = '';
    alertContainer.appendChild(alert);
    
    setTimeout(() => {
        alert.style.opacity = '0';
        setTimeout(() => alert.remove(), 300);
    }, 5000);
}

function updateProgress(percent) {
    progressFill.style.width = `${percent}%`;
}

// File Upload Handlers
uploadZone.addEventListener('click', () => {
    fileInput.click();
});

uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
});

uploadZone.addEventListener('dragleave', () => {
    uploadZone.classList.remove('dragover');
});

uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    
    const files = e.dataTransfer.files;
    if (files.length > 0 && files[0].type === 'application/pdf') {
        handleFileUpload(files[0]);
    } else {
        showAlert('Please upload a PDF file', 'error');
    }
});

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFileUpload(e.target.files[0]);
    }
});

// Upload PDF
async function handleFileUpload(file) {
    const formData = new FormData();
    formData.append('pdf_file', file);
    
    uploadProgress.style.display = 'block';
    updateProgress(30);
    
    try {
        const response = await fetch('/upload/', {
            method: 'POST',
            body: formData
        });
        
        updateProgress(70);
        const data = await response.json();
        
        updateProgress(100);
        
        if (data.status === 'success') {
            currentPdfId = data.pdf_id;
            showAlert(`PDF uploaded successfully! ${data.total_pages} pages detected.`, 'success');
            
            // Update PDF info
            document.getElementById('pdf-filename').textContent = data.filename;
            document.getElementById('pdf-pages').textContent = data.total_pages;
            document.getElementById('pdf-id').textContent = data.pdf_id;
            
            pdfInfoSection.style.display = 'block';
            
            // Update stats
            updateStats();
        } else if (data.status === 'duplicate') {
            currentPdfId = data.pdf_id;
            showAlert('This PDF has already been uploaded', 'info');
            pdfInfoSection.style.display = 'block';
        } else {
            showAlert('Upload failed: ' + data.message, 'error');
        }
    } catch (error) {
        showAlert('Upload error: ' + error.message, 'error');
    } finally {
        setTimeout(() => {
            uploadProgress.style.display = 'none';
            updateProgress(0);
        }, 1000);
    }
}

// Auto-detect sections
autoDetectBtn.addEventListener('click', async () => {
    if (!currentPdfId) {
        showAlert('Please upload a PDF first', 'error');
        return;
    }
    
    autoDetectBtn.disabled = true;
    autoDetectBtn.innerHTML = '<div class="spinner" style="width: 20px; height: 20px; margin: 0;"></div> Detecting...';
    
    try {
        const response = await fetch(`/pdf/${currentPdfId}/auto-detect/`);
        const data = await response.json();
        
        if (data.status === 'success') {
            detectedSections = data.sections;
            showAlert(`Detected ${data.total_sections} patient sections!`, 'success');
            displaySections(data.sections);
            sectionsSection.style.display = 'block';
        } else {
            showAlert('Auto-detection failed', 'error');
        }
    } catch (error) {
        showAlert('Detection error: ' + error.message, 'error');
    } finally {
        autoDetectBtn.disabled = false;
        autoDetectBtn.innerHTML = '🔍 Auto-Detect Sections';
    }
}); // Display detected sections
function displaySections(sections) {
    const sectionsList = document.getElementById('sections-list');
    sectionsList.innerHTML = '';
    
    sections.forEach((section, index) => {
        const sectionDiv = document.createElement('div');
        sectionDiv.className = 'section-item fade-in';
        
        const patientInfo = section.patient_info || {};
        
        sectionDiv.innerHTML = `
            <div class="section-header">
                <h3 style="color: var(--primary-light);">Section ${index + 1}</h3>
                <span class="badge badge-pending">Pages ${section.start_page}-${section.end_page}</span>
            </div>
            <div class="section-info">
                <div class="info-item">
                    <span class="info-label">Patient ID</span>
                    <span class="info-value">${patientInfo.patient_id || 'Not detected'}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">Patient Name</span>
                    <span class="info-value">${patientInfo.name || 'Not detected'}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">Date</span>
                    <span class="info-value">${patientInfo.date || 'Not detected'}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">Contact</span>
                    <span class="info-value">${patientInfo.contact || 'Not detected'}</span>
                </div>
            </div>
        `;
        
        sectionsList.appendChild(sectionDiv);
    });
}

// Create PDF sets
createSetsBtn.addEventListener('click', async () => {
    if (detectedSections.length === 0) {
        showAlert('No sections detected. Run auto-detection first.', 'error');
        return;
    }
    
    createSetsBtn.disabled = true;
    createSetsBtn.innerHTML = '<div class="spinner" style="width: 20px; height: 20px; margin: 0;"></div> Creating...';
    
    try {
        const response = await fetch('/create-sets/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                pdf_id: currentPdfId,
                sections: detectedSections
            })
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            createdSets = data.created_sets;
            showAlert(`Created ${data.count} PDF sets!`, 'success');
            displaySets(data.created_sets);
            setsSection.style.display = 'block';
            updateStats();
        } else {
            showAlert('Failed to create sets', 'error');
        }
    } catch (error) {
        showAlert('Error: ' + error.message, 'error');
    } finally {
        createSetsBtn.disabled = false;
        createSetsBtn.innerHTML = '✅ Create PDF Sets';
    }
});

// Display PDF sets
function displaySets(sets) {
    const setsList = document.getElementById('sets-list');
    setsList.innerHTML = '';
    
    sets.forEach((set) => {
        const setDiv = document.createElement('div');
        setDiv.className = 'section-item fade-in';
        setDiv.id = `set-${set.id}`;
        
        setDiv.innerHTML = `
            <div class="section-header">
                <h3 style="color: var(--primary-light);">${set.patient_name}</h3>
                <div>
                    <span class="badge badge-pending" id="status-${set.id}">PENDING</span>
                    <button class="btn btn-primary" onclick="processSet(${set.id})" id="btn-${set.id}">
                        ⚡ Process
                    </button>
                </div>
            </div>
            <div class="section-info">
                <div class="info-item">
                    <span class="info-label">Pages</span>
                    <span class="info-value">${set.pages}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">Set ID</span>
                    <span class="info-value">${set.id}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">Drive Link</span>
                    <span class="info-value" id="link-${set.id}">Processing...</span>
                </div>
            </div>
        `;
        
        setsList.appendChild(setDiv);
    });
}

// Process single set
async function processSet(setId) {
    const btn = document.getElementById(`btn-${setId}`);
    const statusBadge = document.getElementById(`status-${setId}`);
    
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner" style="width: 15px; height: 15px; margin: 0;"></div>';
    statusBadge.className = 'badge badge-processing';
    statusBadge.textContent = 'PROCESSING';
    
    try {
        const response = await fetch(`/set/${setId}/process/`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.status === 'queued') {
            showAlert(`Set ${setId} queued for processing`, 'info');
            // Poll for status
            pollSetStatus(setId);
        }
    } catch (error) {
        showAlert('Processing error: ' + error.message, 'error');
        statusBadge.className = 'badge badge-failed';
        statusBadge.textContent = 'FAILED';
        btn.disabled = false;
        btn.innerHTML = '⚡ Retry';
    }
}

// Poll set status
async function pollSetStatus(setId) {
    const statusBadge = document.getElementById(`status-${setId}`);
    const linkElement = document.getElementById(`link-${setId}`);
    const btn = document.getElementById(`btn-${setId}`);
    
    const interval = setInterval(async () => {
        try {
            const response = await fetch(`/set/${setId}/status/`);
            const data = await response.json();
            
            if (data.state === 'UPLOADED' || data.state === 'DUPLICATE') {
                statusBadge.className = 'badge badge-uploaded';
                statusBadge.textContent = data.state;
                
                if (data.drive_link) {
                    linkElement.innerHTML = `<a href="${data.drive_link}" target="_blank" style="color: var(--primary-light);">Open in Drive</a>`;
                }
                
                btn.style.display = 'none';
                clearInterval(interval);
                updateStats();
                showAlert(`Set ${setId} uploaded successfully!`, 'success');
            } else if (data.state === 'FAILED') {
                statusBadge.className = 'badge badge-failed';
                statusBadge.textContent = 'FAILED';
                linkElement.textContent = data.error || 'Processing failed';
                btn.disabled = false;
                btn.innerHTML = '⚡ Retry';
                clearInterval(interval);
            }
        } catch (error) {
            console.error('Status poll error:', error);
        }
    }, 3000); // Poll every 3 seconds
}

// Process all sets
processAllBtn.addEventListener('click', () => {
    createdSets.forEach(set => {
        processSet(set.id);
    });
});

// Load and display patients
async function loadPatients() {
    try {
        const response = await fetch('/patients/');
        const data = await response.json();
        
        if (data.status === 'success') {
            displayPatients(data.patients);
        }
    } catch (error) {
        console.error('Error loading patients:', error);
    }
}

function displayPatients(patients) {
    const patientsList = document.getElementById('patients-list');
    
    if (patients.length === 0) {
        patientsList.innerHTML = '<p style="text-align: center; color: var(--text-muted);">No patients yet. Upload and process PDFs to get started.</p>';
        return;
    }
    
    patientsList.innerHTML = '';
    
    patients.forEach(patient => {
        const patientDiv = document.createElement('div');
        patientDiv.className = 'section-item fade-in';
        
        patientDiv.innerHTML = `
            <div class="section-header">
                <h3 style="color: var(--primary-light);">${patient.name}</h3>
                <button class="btn btn-success" onclick="generateSummary('${patient.patient_id}')">
                    📄 Generate Summary
                </button>
            </div>
            <div class="section-info">
                <div class="info-item">
                    <span class="info-label">Patient ID</span>
                    <span class="info-value">${patient.patient_id}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">Address</span>
                    <span class="info-value">${patient.address || 'N/A'}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">Contact</span>
                    <span class="info-value">${patient.contact || 'N/A'}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">PDF Sets</span>
                    <span class="info-value">${patient.uploaded_sets}/${patient.total_sets} uploaded</span>
                </div>
            </div>
        `;
        
        patientsList.appendChild(patientDiv);
    });
}

// Generate summary document
async function generateSummary(patientId) {
    showAlert('Generating summary document...', 'info');
    
    try {
        const response = await fetch(`/patient/${patientId}/summary/`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            showAlert('Summary generated successfully!', 'success');
            
            // Create download link
            const downloadLink = document.createElement('a');
            downloadLink.href = data.download_url;
            downloadLink.download = `summary_${patientId}.docx`;
            downloadLink.click();
        } else {
            showAlert('Failed to generate summary: ' + data.message, 'error');
        }
    } catch (error) {
        showAlert('Error: ' + error.message, 'error');
    }
}

// Update stats
async function updateStats() {
    // Reload page to update stats (or implement AJAX call to get updated stats)
    location.reload();
}

// Refresh patients
refreshPatientsBtn.addEventListener('click', loadPatients);

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadPatients();
});
