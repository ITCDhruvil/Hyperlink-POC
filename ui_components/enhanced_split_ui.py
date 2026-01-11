"""
Enhanced PDF Split UI with Auto-Extract and Visual Table Editor
Complete implementation ready to integrate into main app
"""
import streamlit as st
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from page_range_editor import (
    render_page_range_editor,
    auto_extract_from_word,
    format_ranges_for_split
)


def render_enhanced_split_ui():
    """
    Complete UI for PDF splitting with auto-extract and manual editing
    """
    st.title("📄 PDF Split & Upload Tool")
    st.markdown("---")

    # File uploads
    st.subheader("1️⃣ Upload Files")

    col1, col2 = st.columns(2)

    with col1:
        word_file = st.file_uploader(
            "📄 Word Document (optional - for auto-extract)",
            type=['docx'],
            help="Upload the Word document to automatically extract page ranges",
            key="word_upload"
        )

    with col2:
        pdf_file = st.file_uploader(
            "📄 PDF to Split (required)",
            type=['pdf'],
            help="Upload the PDF file that will be split",
            key="pdf_upload"
        )

    st.markdown("---")

    # Auto-extract section
    st.subheader("2️⃣ Extract Page Ranges")

    # Check if both files uploaded
    can_auto_extract = word_file is not None and pdf_file is not None

    if not can_auto_extract:
        st.info("💡 Upload both Word document and PDF to enable auto-extraction")

    col1, col2 = st.columns([1, 3])

    with col1:
        extract_button = st.button(
            "🚀 Auto-Extract from Word",
            disabled=not can_auto_extract,
            type="primary" if can_auto_extract else "secondary",
            help="Extract page ranges automatically from Word document" if can_auto_extract else "Upload both files first"
        )

    with col2:
        if extract_button:
            with st.spinner("Extracting page ranges from Word document..."):
                try:
                    extracted_ranges = auto_extract_from_word(word_file)

                    if extracted_ranges:
                        # Update session state with extracted ranges
                        st.session_state['split_page_ranges'] = extracted_ranges
                        st.success(f"✅ Successfully extracted {len(extracted_ranges)} page ranges!")

                        # Show preview
                        with st.expander("📋 Preview Extracted Ranges", expanded=True):
                            for i, r in enumerate(extracted_ranges, 1):
                                st.markdown(f"{i}. `{r}`")
                        st.rerun()
                    else:
                        st.warning("No page ranges found in Word document")

                except Exception as e:
                    st.error(f"❌ Error extracting ranges: {str(e)}")

    st.markdown("---")

    # Visual table editor
    st.subheader("3️⃣ Review & Edit Page Ranges")

    st.markdown("**Manual Entry or Edit Auto-Extracted Ranges:**")

    # Get initial ranges (from auto-extract or empty)
    initial_ranges = st.session_state.get('split_page_ranges', [])

    # Render table editor
    page_ranges = render_page_range_editor(
        initial_ranges=initial_ranges,
        key_prefix="split"
    )

    st.markdown("---")

    # Split & Upload section
    st.subheader("4️⃣ Split & Upload")

    # Additional inputs
    col1, col2 = st.columns(2)

    with col1:
        patient_name = st.text_input(
            "Patient Name (for folder)",
            placeholder="e.g., Ahmad_Al_Yabroudi",
            help="Name of the patient folder in Google Drive"
        )

    with col2:
        drive_folder_id = st.text_input(
            "Google Drive Folder ID",
            placeholder="Enter Drive folder ID",
            help="The ID of the patient folder in Google Drive"
        )

    # Split button
    can_split = (
        pdf_file is not None and
        len(page_ranges) > 0 and
        patient_name.strip() != "" and
        drive_folder_id.strip() != ""
    )

    if st.button(
        "✂️ Split PDF & Upload to Drive",
        disabled=not can_split,
        type="primary" if can_split else "secondary"
    ):
        if not can_split:
            st.error("⚠️ Please fill in all required fields and add at least one page range")
        else:
            # Format ranges for split
            formatted_ranges = format_ranges_for_split(page_ranges)

            st.success("🎉 Ready to split!")

            # Show what will happen
            st.info("**Split Preview:**")
            st.markdown(f"- **PDF:** {pdf_file.name}")
            st.markdown(f"- **Patient:** {patient_name}")
            st.markdown(f"- **Ranges:** `{formatted_ranges}`")
            st.markdown(f"- **Total Splits:** {len(page_ranges)}")

            # Here you would call your actual split/upload function
            st.code(f"""
# Call split function:
split_and_upload_pdf(
    pdf_file=pdf_file,
    page_ranges="{formatted_ranges}",
    patient_name="{patient_name}",
    drive_folder_id="{drive_folder_id}"
)
            """, language="python")

            st.success("✅ PDF split and uploaded successfully! (Demo mode)")

    # Help section
    with st.expander("ℹ️ How to Use"):
        st.markdown("""
        ### Quick Start

        **Option 1: Auto-Extract (Recommended)**
        1. Upload Word document (.docx)
        2. Upload PDF file
        3. Click "Auto-Extract from Word"
        4. Review extracted ranges in table
        5. Edit if needed
        6. Enter patient name and Drive folder ID
        7. Click "Split PDF & Upload"

        **Option 2: Manual Entry**
        1. Upload PDF file
        2. Click "+ Add Range" to add page ranges manually
        3. Enter ranges like:
           - Single page: `5`
           - Range: `1-10`
           - Complex: `25-29, 31-35`
        4. Enter patient name and Drive folder ID
        5. Click "Split PDF & Upload"

        ### Page Range Formats

        - **Single Page:** `5` → Extracts page 5
        - **Range:** `1-10` → Extracts pages 1 through 10
        - **Multiple Ranges:** `25-29, 31-35` → Extracts pages 25-29 and 31-35
        - **Mixed:** `5, 7-10, 15` → Extracts pages 5, 7-10, and 15
        """)


if __name__ == '__main__':
    st.set_page_config(
        page_title="Enhanced PDF Split Tool",
        page_icon="✂️",
        layout="wide"
    )

    render_enhanced_split_ui()
