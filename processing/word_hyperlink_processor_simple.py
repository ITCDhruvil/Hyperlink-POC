"""
Simple Word Hyperlink Processor

SIMPLE PATTERN:
- Statements have page numbers at the END
- Example: "04/05/13. Progress Note. US HEALTHWORKS. 4-9"
- Extract page number, make whole statement a hyperlink
- Result: "04/05/13. Progress Note. US HEALTHWORKS." (linked to 4-9.pdf)
"""
import re
from typing import Optional, Dict
from docx import Document
from docx.shared import Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from .drive_utils import get_drive_service


def _normalize_page_spec(s: str) -> str:
    s = (s or '').replace('\u00a0', ' ').strip()
    s = s.replace('–', '-').replace('—', '-').replace('‑', '-')
    # Normalize spaces around dashes in page ranges: "1 - 2" -> "1-2"
    s = re.sub(r'(\d+)\s*-\s*(\d+)', r'\1-\2', s)
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*,\s*', ', ', s)
    s = s.strip()
    if not _is_page_spec(s):
        return s

    parts = [p.strip() for p in s.split(',') if p.strip()]
    normalized_parts = []
    for p in parts:
        m = re.fullmatch(r'(\d+)(?:\s*-\s*(\d+))?', p)
        if not m:
            normalized_parts.append(p)
            continue
        a = str(int(m.group(1)))
        if m.group(2):
            b = str(int(m.group(2)))
            normalized_parts.append(f"{a}-{b}")
        else:
            normalized_parts.append(a)

    return ', '.join(normalized_parts)


def _is_page_spec(s: str) -> bool:
    return bool(re.fullmatch(r'\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*', (s or '').strip()))


def add_hyperlink(paragraph, url, text, color='0563C1', underline=True, bold=False, font_name: str = 'Times New Roman', font_size_pt: int = 12):
    """Add a hyperlink to a paragraph"""
    part = paragraph.part
    r_id = part.relate_to(url, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink', is_external=True)

    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), r_id)

    new_run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')

    # Hyperlink style
    rStyle = OxmlElement('w:rStyle')
    rStyle.set(qn('w:val'), 'Hyperlink')
    rPr.append(rStyle)

    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)
    rFonts.set(qn('w:eastAsia'), font_name)
    rFonts.set(qn('w:cs'), font_name)
    rPr.append(rFonts)

    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), str(int(font_size_pt) * 2))
    rPr.append(sz)

    szCs = OxmlElement('w:szCs')
    szCs.set(qn('w:val'), str(int(font_size_pt) * 2))
    rPr.append(szCs)

    # Color
    c = OxmlElement('w:color')
    c.set(qn('w:val'), color)
    rPr.append(c)

    # Underline
    if underline:
        u = OxmlElement('w:u')
        u.set(qn('w:val'), 'single')
        rPr.append(u)

    if bold:
        b = OxmlElement('w:b')
        rPr.append(b)

    new_run.append(rPr)

    # Text
    t = OxmlElement('w:t')
    t.text = text
    new_run.append(t)

    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)

    return hyperlink


class WordHyperlinkProcessorSimple:
    """
    Simple processor for statements with page numbers at the end
    """

    def __init__(self):
        self.drive_service = get_drive_service()

    def extract_page_ranges_from_document(self, doc: Document) -> list:
        """
        Extract all page ranges from a Word document.

        Scans the document for statements (lines starting with dates) and
        extracts their page numbers. Returns list of page ranges in order.

        Args:
            doc: python-docx Document object

        Returns:
            List of page ranges as strings (e.g., ['1-2', '4', '7-8', ...])

        Example:
            processor = WordHyperlinkProcessorSimple()
            doc = Document('patient_record.docx')
            ranges = processor.extract_page_ranges_from_document(doc)
            # Returns: ['1-2', '4', '7-8', '11-15', ...]

            # Format for PDF split:
            formatted = ';'.join(ranges)
            # Returns: '1-2;4;7-8;11-15'
        """
        page_ranges = []
        seen_ranges = set()

        # Get all paragraphs (body + tables)
        all_paragraphs = []
        for p in doc.paragraphs:
            all_paragraphs.append(p.text)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        all_paragraphs.append(p.text)

        # Process each paragraph
        for text in all_paragraphs:
            if not text or not text.strip():
                continue

            # Check if it's a statement line
            if not self.is_statement_line(text):
                continue

            # Extract page range
            result = self.parse_statement_with_page_number(text)
            if not result or not result.get('page_range'):
                continue

            page_range = result['page_range']

            # Avoid duplicates
            if page_range not in seen_ranges:
                page_ranges.append(page_range)
                seen_ranges.add(page_range)

        return page_ranges

    def extract_page_ranges_from_file(self, docx_path: str) -> list:
        """
        Extract page ranges from a Word document file path.

        Convenience method that opens the document and extracts ranges.

        Args:
            docx_path: Path to .docx file

        Returns:
            List of page ranges as strings

        Example:
            processor = WordHyperlinkProcessorSimple()
            ranges = processor.extract_page_ranges_from_file('patient.docx')
            formatted = ';'.join(ranges)  # For PDF split
        """
        doc = Document(docx_path)
        return self.extract_page_ranges_from_document(doc)

    def extract_patient_name_from_document(self, doc: Document) -> Optional[str]:
        """
        Extract patient name from document header
        Looks for: "PATIENT NAME: CARL MAYFIELD"
        """
        for paragraph in doc.paragraphs[:10]:
            text = paragraph.text.strip()

            # Pattern: "PATIENT NAME: CARL MAYFIELD"
            match = re.search(r'PATIENT\s+NAME:?\s+(.+)', text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Convert to folder format
                name = name.title().replace(' ', '_')
                return name

            # Pattern: "Name: Carl Mayfield"
            match = re.search(r'^Name:?\\s+(.+)', text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                name = name.title().replace(' ', '_')
                return name

        return None

    def parse_statement_with_page_number(self, text: str) -> Optional[Dict]:
        """
        Parse statement to extract page number

        Pattern: "DATE.  DESCRIPTION. PAGE_NUMBERS ADDITIONAL_TEXT"
        Example: "06/19/25.  From EMANATE HEALTH...  Attestation. 1-2 Attesting to 422 pages..."

        The page numbers appear after the last period in the description, followed by optional text.

        Returns:
            {
                'page_range': '1-2',
                'header_text': '06/19/25.  From EMANATE HEALTH...  Attestation.',
                'remainder_text': 'Attesting to 422 pages...',
                'original_text': 'original...'
            }
        """
        text = _normalize_page_spec(text)

        # Pattern: find page numbers that appear after a period/space
        # Page spec: digit or range (1-2) or multiple ranges (25-29, 31-35)
        page_spec_pattern = re.compile(r'(?P<pages>\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*)')

        best = None
        for m in page_spec_pattern.finditer(text):
            start, end = m.start('pages'), m.end('pages')

            # Reject if part of a date like "06/19/25"
            if end < len(text) and text[end] == '/':
                continue
            if start > 0 and text[start - 1] == '/':
                continue

            # Reject if part of a decimal number like "0.9" or "164.5"
            if start > 0 and text[start - 1] == '.':
                continue

            # Reject if part of numbered list like "3) Renal mass"
            if end < len(text) and text[end] == ')':
                continue

            pages_raw = (m.group('pages') or '').strip()
            if not _is_page_spec(pages_raw):
                continue

            # Check if this appears after a period or colon (common separators)
            # Look backwards to find the nearest punctuation
            if start > 0:
                # Find what comes before the page number
                before = text[:start].rstrip()
                if not before:
                    continue

                # Page numbers should appear after punctuation (period, colon) or space
                if not (before.endswith('.') or before.endswith(':') or before.endswith(' ')):
                    continue

                # Reject if preceded by measurement labels like "SpO2: " or "BP: "
                # Check last 10 chars before the number
                context_before = before[-15:] if len(before) >= 15 else before
                if re.search(r'(SpO2|BP|Pulse|Temp|Weight|RR|P|T):\s*$', context_before, re.IGNORECASE):
                    continue

            # Page numbers appear early in statements (within first ~200 chars)
            # Medical details with numbers appear much later
            # Use position check to prefer earlier matches
            if start > 250:
                # Only accept this if we haven't found anything yet
                if best is not None:
                    continue

            # Use the FIRST valid page spec match (not the last)
            # Page numbers appear early, medical details with numbers come later
            if best is None:
                best = m

        if best:
            page_spec_raw = (best.group('pages') or '').strip()
            page_spec = _normalize_page_spec(page_spec_raw)

            # Everything before page numbers is the header (description to be hyperlinked)
            header_text = text[:best.start('pages')].strip()

            # Everything after page numbers is remainder text (kept but not hyperlinked)
            remainder_text = text[best.end('pages'):].strip()

            # Cleanup spacing
            def _normalize_spacing(s: str) -> str:
                s = re.sub(r'\s+', ' ', s)
                s = re.sub(r'\s+([\.,;:])', r'\1', s)
                s = re.sub(r'([\.,;:])(?=\S)', r'\1 ', s)
                return s.strip()

            header_text = _normalize_spacing(header_text)
            remainder_text = _normalize_spacing(remainder_text)

            # Ensure header ends with period for consistency
            if header_text and not header_text.endswith('.'):
                header_text += '.'

            return {
                'page_range': page_spec,
                'header_text': header_text,
                'remainder_text': remainder_text,
                'original_text': text
            }

        return None

    def is_statement_line(self, text: str) -> bool:
        """
        Check if line is a statement (starts with date)

        Patterns:
        - "06/19/25.  From EMANATE HEALTH..."
        - "08/26/22.  EMANATE HEALTH..."

        Must start with DATE (no numbering prefix required)
        """
        text = (text or '').replace('\u00a0', ' ').strip()
        # Pattern: starts with date MM/DD/YY or MM/DD/YYYY followed by dot and spaces
        return bool(re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}\.\s+', text))

    def _iter_all_paragraphs(self, doc: Document):
        # Yield normal body paragraphs
        for p in doc.paragraphs:
            yield p

        # Yield paragraphs inside tables (common in generated Word docs)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        yield p

    def _apply_default_font(self, doc: Document, font_name: str = 'Times New Roman', font_size_pt: int = 12) -> None:
        normal = doc.styles['Normal']
        normal.font.name = font_name
        normal.font.size = Pt(font_size_pt)
        if normal._element.rPr is not None and normal._element.rPr.rFonts is not None:
            normal._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)

        for p in self._iter_all_paragraphs(doc):
            for run in p.runs:
                run.font.name = font_name
                run.font.size = Pt(font_size_pt)
                if run._element is not None and run._element.rPr is not None and run._element.rPr.rFonts is not None:
                    run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)

    def _remove_paragraph_borders(self, paragraph) -> None:
        pPr = paragraph._p.pPr
        if pPr is None:
            return
        pBdr = pPr.find(qn('w:pBdr'))
        if pBdr is not None:
            pPr.remove(pBdr)

    def _normalize_tables(self, doc: Document) -> None:
        for table in doc.tables:
            try:
                table.style = 'Table Grid'
            except Exception:
                pass

            tbl = table._tbl
            tblPr = tbl.tblPr
            if tblPr is None:
                continue

            existing_borders = tblPr.find(qn('w:tblBorders'))
            if existing_borders is not None:
                tblPr.remove(existing_borders)

            borders = OxmlElement('w:tblBorders')

            def _add_border(tag: str):
                el = OxmlElement(tag)
                el.set(qn('w:val'), 'single')
                el.set(qn('w:sz'), '4')
                el.set(qn('w:space'), '0')
                el.set(qn('w:color'), 'auto')
                return el

            borders.append(_add_border('w:top'))
            borders.append(_add_border('w:left'))
            borders.append(_add_border('w:bottom'))
            borders.append(_add_border('w:right'))
            borders.append(_add_border('w:insideH'))
            borders.append(_add_border('w:insideV'))

            tblPr.append(borders)

            # Clear cell shading/borders that can appear as thick black/gray bands
            for row in table.rows:
                for cell in row.cells:
                    tcPr = cell._tc.tcPr
                    if tcPr is None:
                        continue

                    shd = tcPr.find(qn('w:shd'))
                    if shd is not None:
                        tcPr.remove(shd)

                    tcBorders = tcPr.find(qn('w:tcBorders'))
                    if tcBorders is not None:
                        tcPr.remove(tcBorders)

    def get_pdfs_from_drive_folder(self, drive_folder_id: str) -> Dict[str, str]:
        """Get all PDF files from Drive folder"""
        pdf_links = {}

        try:
            results = self.drive_service.service.files().list(
                q=f"'{drive_folder_id}' in parents and mimeType='application/pdf' and trashed=false",
                fields="files(id, name, webViewLink)",
                pageSize=1000,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True
            ).execute()

            files = results.get('files', [])

            for file in files:
                filename = file['name']
                if not filename.lower().endswith('.pdf'):
                    continue

                stem = filename[:-4]
                key = _normalize_page_spec(stem)
                if _is_page_spec(key):
                    pdf_links[key] = file['webViewLink']

            return pdf_links

        except Exception as e:
            raise Exception(f"Failed to fetch PDFs: {str(e)}")

    def process_word_document(
        self,
        input_docx_path: str,
        pdf_links: Dict[str, str],
        output_docx_path: Optional[str] = None
    ) -> Dict:
        """
        Process Word document - SIMPLE PATTERN

        Logic:
        1. Find statement with page number at end
        2. Extract page number
        3. Replace whole statement with hyperlink (without page number)
        """
        if output_docx_path is None:
            output_docx_path = input_docx_path

        doc = Document(input_docx_path)
        self._apply_default_font(doc, font_name='Times New Roman', font_size_pt=12)

        stats = {
            'total_statements': 0,
            'linked_statements': 0,
            'unlinked_statements': 0,
            'statements': []
        }

        debug_first_lines = []
        debug_date_matches = 0
        debug_parsed_matches = 0

        for paragraph in self._iter_all_paragraphs(doc):
            raw_text = paragraph.text
            if not raw_text or not raw_text.strip():
                continue

            if len(debug_first_lines) < 40:
                debug_first_lines.append(raw_text)

            def _split_statement_chunks(s: str):
                s = (s or '').replace('\u00a0', ' ').strip()
                if not s:
                    return []

                # First, try line-break based splitting
                parts = [ln.strip() for ln in s.splitlines() if ln.strip()]
                if len(parts) > 1:
                    return parts

                # Fallback: some Word docs have multiple statements in one paragraph without line breaks.
                # Split by repeated date occurrences (no numbering prefix)
                start_re = re.compile(r'(?:^|\s)\d{1,2}/\d{1,2}/\d{2,4}\.\s+')
                matches = list(start_re.finditer(s))
                if len(matches) <= 1:
                    return [s]

                chunks = []
                for i, m in enumerate(matches):
                    start = m.start()
                    if start > 0 and s[start].isspace():
                        start += 1
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(s)
                    chunk = s[start:end].strip()
                    if chunk:
                        chunks.append(chunk)
                return chunks

            lines = _split_statement_chunks(raw_text)
            if not lines:
                continue

            processed_lines = []
            had_any_statement = False

            for line in lines:
                normalized_line = (line or '').replace('\u00a0', ' ').replace('–', '-').replace('—', '-')

                if not self.is_statement_line(normalized_line):
                    processed_lines.append({'kind': 'text', 'text': line})
                    continue

                debug_date_matches += 1

                statement_info = self.parse_statement_with_page_number(normalized_line)
                if not statement_info:
                    processed_lines.append({'kind': 'text', 'text': line})
                    continue

                debug_parsed_matches += 1

                had_any_statement = True
                stats['total_statements'] += 1
                page_range = statement_info['page_range']
                header_text = statement_info.get('header_text', '')
                remainder_text = statement_info.get('remainder_text', '')

                if page_range in pdf_links:
                    drive_link = pdf_links[page_range]
                    stats['linked_statements'] += 1
                    processed_lines.append({
                        'kind': 'segments',
                        'segments': [
                            {'kind': 'link', 'text': header_text, 'url': drive_link},
                            {'kind': 'text', 'text': ((' ' + remainder_text) if remainder_text else '')},
                        ],
                        'page_range': page_range,
                    })
                    stats['statements'].append({
                        'page_range': page_range,
                        'text': header_text,
                        'status': 'linked',
                        'drive_link': drive_link
                    })
                else:
                    stats['unlinked_statements'] += 1
                    # Keep header + remainder as plain text, but remove the page range itself
                    combined = (header_text + ((' ' + remainder_text) if remainder_text else '')).strip()
                    processed_lines.append({'kind': 'text', 'text': combined, 'page_range': page_range})
                    stats['statements'].append({
                        'page_range': page_range,
                        'text': header_text,
                        'status': 'not_found',
                        'reason': f'No PDF found for pages {page_range}'
                    })

            # If nothing looked like a statement, don't modify this paragraph
            if not had_any_statement:
                continue

            # Rebuild paragraph content with hyperlinks and line breaks
            paragraph.clear()
            self._remove_paragraph_borders(paragraph)
            for idx, item in enumerate(processed_lines):
                if item.get('kind') == 'segments':
                    for seg in item.get('segments', []):
                        if seg.get('kind') == 'link':
                            add_hyperlink(
                                paragraph,
                                seg['url'],
                                seg['text'],
                                color='0563C1',
                                underline=True,
                                bold=True,
                                font_name='Times New Roman',
                                font_size_pt=12
                            )
                        else:
                            run = paragraph.add_run(seg.get('text', ''))
                            run.font.name = 'Times New Roman'
                            run.font.size = Pt(12)
                else:
                    run = paragraph.add_run(item.get('text', ''))
                    run.font.name = 'Times New Roman'
                    run.font.size = Pt(12)

                if idx < len(processed_lines) - 1:
                    paragraph.add_run().add_break()

        self._apply_default_font(doc, font_name='Times New Roman', font_size_pt=12)
        self._normalize_tables(doc)

        # Save document
        doc.save(output_docx_path)

        if stats['total_statements'] == 0:
            print("=" * 80)
            print("[DEBUG] No statements detected in DOCX for linking")
            print(f"[DEBUG] Date-like lines matched: {debug_date_matches}")
            print(f"[DEBUG] Lines parsed with page ranges: {debug_parsed_matches}")
            print("[DEBUG] First extracted text blocks (repr):")
            for i, t in enumerate(debug_first_lines[:20]):
                print(f"  {i+1:02d}: {repr(t)}")
            print("=" * 80)

        return stats
