"""
Utility functions for PDF processing
"""
import hashlib
import re
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter
from typing import Tuple, List, Dict
import pytesseract
from PIL import Image
import io


def compute_sha256(file_path: str) -> str:
    """Compute SHA-256 hash of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def get_pdf_page_count(file_path: str) -> int:
    """Get total number of pages in a PDF"""
    reader = PdfReader(file_path)
    return len(reader.pages)


def extract_text_from_page(pdf_path: str, page_num: int) -> str:
    """Extract text from a specific page (0-indexed)"""
    try:
        reader = PdfReader(pdf_path)
        if page_num < len(reader.pages):
            page = reader.pages[page_num]
            return page.extract_text()
        return ""
    except Exception as e:
        print(f"Error extracting text from page {page_num}: {e}")
        return ""


def extract_patient_info(text: str) -> Dict[str, str]:
    """
    Extract patient information from text using regex patterns
    Returns dict with: patient_id, name, date, address, contact
    """
    info = {
        'patient_id': '',
        'name': '',
        'date': '',
        'address': '',
        'contact': ''
    }
    
    # Pattern for patient ID - Look for actual ID patterns (numbers, letters, hyphens)
    # Try multiple patterns in order of specificity
    patient_id_match = re.search(r'(?:Patient\s*ID|Patient\s*No)[:\s]+([A-Z0-9-]+)', text, re.IGNORECASE)
    if not patient_id_match:
        # Fallback: Look for "ID:" followed by alphanumeric
        patient_id_match = re.search(r'\bID[:\s]+([A-Z0-9-]{3,})', text, re.IGNORECASE)
    if patient_id_match:
        extracted_id = patient_id_match.group(1).strip()
        # Validate: ID should not be common words like "and", "the", etc.
        if len(extracted_id) >= 3 and not extracted_id.lower() in ['and', 'the', 'for', 'with']:
            info['patient_id'] = extracted_id
    
    # Pattern for name - Stop at newline or common header keywords
    # Use negative lookahead to stop before "Address", "DOB", "Date", etc.
    name_match = re.search(
        r'(?:Patient\s*Name|Name)[:\s]+([A-Za-z\s\.]+?)(?=\s*(?:Address|DOB|Date|Phone|Contact|SSN|\n|$))',
        text,
        re.IGNORECASE
    )
    if name_match:
        raw_name = name_match.group(1).strip()
        # Remove extra whitespace and limit length
        info['name'] = re.sub(r'\s+', ' ', raw_name)[:50]
    
    # Pattern for date (MM/DD/YYYY or DD/MM/YYYY)
    date_match = re.search(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b', text)
    if date_match:
        info['date'] = date_match.group(1)
    
    # Pattern for contact/phone
    contact_match = re.search(r'(?:Phone|Contact|Mobile)[:\s]+([\d\s\-\+\(\)]+)', text, re.IGNORECASE)
    if contact_match:
        info['contact'] = contact_match.group(1).strip()
    
    # Pattern for address (basic - customize as needed)
    address_match = re.search(r'(?:Address)[:\s]+([^\n]+)', text, re.IGNORECASE)
    if address_match:
        info['address'] = address_match.group(1).strip()
    
    return info


def detect_section_type(text: str) -> str:
    """
    Detect the type of medical document section
    Returns section type (e.g., 'Cover_Letter', 'Attestation', 'Medical_Records', etc.)
    """
    text_upper = text.upper()

    # Check for specific section types in priority order
    if 'COVER LETTER' in text_upper or 'COVERING LETTER' in text_upper:
        return 'Cover_Letter'
    elif 'ATTESTATION' in text_upper:
        return 'Attestation'
    elif 'MEDICAL RECORD' in text_upper or 'PROGRESS NOTE' in text_upper or 'DOCTOR\'S FIRST REPORT' in text_upper:
        return 'Medical_Records'
    elif 'DISCHARGE SUMMARY' in text_upper:
        return 'Discharge_Summary'
    elif 'LAB REPORT' in text_upper or 'LABORATORY' in text_upper:
        return 'Lab_Reports'
    elif 'RADIOLOGY' in text_upper or 'IMAGING' in text_upper or 'X-RAY' in text_upper:
        return 'Radiology'
    elif 'PRESCRIPTION' in text_upper or 'MEDICATION' in text_upper:
        return 'Prescriptions'
    elif 'MISCELLANEOUS' in text_upper:
        return 'Miscellaneous'
    else:
        # Default fallback
        return 'Medical_Records'


def detect_section_boundaries(pdf_path: str) -> List[Dict]:
    """
    Auto-detect patient sections in PDF with section type detection
    Returns list of dicts with: start_page, end_page, patient_info, section_type
    """
    reader = PdfReader(pdf_path)
    total_pages = len(reader.pages)
    sections = []
    current_section = None

    for page_num in range(total_pages):
        text = extract_text_from_page(pdf_path, page_num)

        # Check if this page starts a new patient section
        # Look for common headers like "Patient Report", "Medical Record", etc.
        is_new_section = any(keyword in text.upper() for keyword in [
            'PATIENT REPORT',
            'MEDICAL RECORD',
            'PATIENT NAME',
            'PATIENT ID',
            'DISCHARGE SUMMARY',
            'COVER LETTER',
            'ATTESTATION'
        ])

        if is_new_section:
            # Close previous section
            if current_section:
                current_section['end_page'] = page_num
                sections.append(current_section)

            # Start new section
            patient_info = extract_patient_info(text)
            section_type = detect_section_type(text)

            current_section = {
                'start_page': page_num + 1,  # 1-indexed for display
                'end_page': page_num + 1,
                'patient_info': patient_info,
                'section_type': section_type
            }

    # Close last section
    if current_section:
        current_section['end_page'] = total_pages
        sections.append(current_section)

    return sections


def split_pdf(input_path: str, output_path: str, start_page: int, end_page: int) -> Tuple[str, str]:
    """
    Split PDF and save to output path
    Args:
        input_path: Path to original PDF
        output_path: Path to save split PDF
        start_page: Starting page (1-indexed)
        end_page: Ending page (1-indexed, inclusive)
    Returns:
        Tuple of (output_path, sha256_hash)
    """
    reader = PdfReader(input_path)
    writer = PdfWriter()
    
    # Convert to 0-indexed and add pages
    for page_num in range(start_page - 1, end_page):
        if page_num < len(reader.pages):
            writer.add_page(reader.pages[page_num])
    
    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Write PDF
    with open(output_path, 'wb') as output_file:
        writer.write(output_file)
    
    # Compute hash
    sha256 = compute_sha256(output_path)
    
    return output_path, sha256


def merge_pdf_segments(input_path: str, output_path: str, segments: List[Tuple[int, int]]) -> Tuple[str, str]:
    reader = PdfReader(input_path)
    writer = PdfWriter()

    for start_page, end_page in segments:
        for page_num in range(start_page - 1, end_page):
            if page_num < len(reader.pages):
                writer.add_page(reader.pages[page_num])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'wb') as output_file:
        writer.write(output_file)

    sha256 = compute_sha256(output_path)
    return output_path, sha256


def create_folder_structure(base_path: Path, year: int, month: int, day: int, 
                           hospital: str, patient_id: str, patient_name: str, 
                           original_filename: str) -> Path:
    """
    Create hierarchical folder structure
    Returns the full path to the folder
    """
    # Sanitize names for filesystem
    hospital = re.sub(r'[<>:"/\\|?*]', '_', hospital)
    patient_name = re.sub(r'[<>:"/\\|?*]', '_', patient_name)
    
    folder_path = (
        base_path / 
        str(year) / 
        f"{month:02d}" / 
        f"{day:02d}" / 
        hospital / 
        f"{patient_id}_{patient_name}" / 
        original_filename
    )
    
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path


def generate_section_summary(pdf_path: str, start_page: int, end_page: int, max_length: int = 300) -> tuple:
    """
    Generate a brief summary of a PDF section by extracting key medical information
    
    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page (1-indexed)
        end_page: Ending page (1-indexed)
        max_length: Maximum summary length in characters
    
    Returns:
        Tuple of (summary_string, doctor_name)
    """
    try:
        # Extract text from the section
        full_text = ""
        for page_num in range(start_page - 1, end_page):
            text = extract_text_from_page(pdf_path, page_num)
            full_text += text + " "
        
        if not full_text.strip():
            return ("(No text content available)", "")
        
        # Extract doctor name first
        doctor_name = ""
        # Pattern: "Name, Credential" or "Name, MD" etc.
        doctor_match = re.search(r'([A-Z][a-z]+\s+[A-Z][a-z]+),?\s+(MD|DO|NP|PA|DPM|DC)\b', full_text)
        if doctor_match:
            doctor_name = f"{doctor_match.group(1)}, {doctor_match.group(2)}"
        
        # Extract key information patterns
        summary_parts = []
        
        # 1. Date
        date_match = re.search(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b', full_text)
        if date_match:
            summary_parts.append(date_match.group(1))
        
        # 2. Document type
        doc_types = ['Progress Note', 'Doctor\'s First Report', 'Emergency Department', 
                     'Physician\'s Progress', 'Discharge Summary', 'Medical Record']
        for doc_type in doc_types:
            if doc_type.upper() in full_text.upper():
                summary_parts.append(doc_type)
                break
        
        # 3. Hospital/Facility
        facility_match = re.search(r'(?:Hospital|Medical Center|Clinic|HealthWorks|Kaiser|Concentra)[:\s]*([A-Z][A-Za-z\s]+?)(?:\.|DOI|Subjective)', full_text, re.IGNORECASE)
        if facility_match:
            facility = facility_match.group(0).strip()[:50]
            summary_parts.append(facility)
        
        # 4. Chief complaint or HPI
        hpi_match = re.search(r'(?:HPI|Chief Complaint|Subjective)[:\s]+([^\.]+\.)', full_text, re.IGNORECASE)
        if hpi_match:
            hpi = hpi_match.group(1).strip()[:150]
            summary_parts.append(f"HPI: {hpi}")
        
        # 5. Diagnosis
        dx_match = re.search(r'(?:Diagnos[ie]s|Assessment)[:\s]+([^\.]+\.)', full_text, re.IGNORECASE)
        if dx_match:
            dx = dx_match.group(1).strip()[:100]
            summary_parts.append(f"Diagnosis: {dx}")
        
        # 6. Plan/Treatment
        plan_match = re.search(r'(?:Plan|Treatment)[:\s]+([^\.]+\.)', full_text, re.IGNORECASE)
        if plan_match:
            plan = plan_match.group(1).strip()[:100]
            summary_parts.append(f"Plan: {plan}")
        
        # Combine parts
        summary = ".  ".join(summary_parts)
        
        # Truncate if too long
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."
        
        return (summary if summary else "(Summary extraction in progress...)", doctor_name)
        
    except Exception as e:
        return (f"(Error generating summary: {str(e)[:50]})", "")

