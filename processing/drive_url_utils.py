"""
Google Drive URL Utilities
Extract file and folder IDs from Google Drive URLs
"""
import re


def extract_drive_id(input_string):
    """
    Extract file or folder ID from a Google Drive URL.

    Supports various URL formats:
    - Document: https://docs.google.com/document/d/FILE_ID/edit
    - File: https://drive.google.com/file/d/FILE_ID/view
    - Folder: https://drive.google.com/drive/folders/FOLDER_ID
    - Open: https://drive.google.com/open?id=FILE_ID

    If input is already an ID (no http), returns it unchanged.

    Args:
        input_string (str): Google Drive URL or file/folder ID

    Returns:
        str: Extracted ID or original input if no match

    Examples:
        >>> extract_drive_id('https://docs.google.com/document/d/1ABC123/edit')
        '1ABC123'

        >>> extract_drive_id('https://drive.google.com/drive/folders/1XYZ789?usp=drive_link')
        '1XYZ789'

        >>> extract_drive_id('1ABC123')
        '1ABC123'
    """
    if not input_string:
        return input_string

    input_string = input_string.strip()

    # If it's not a URL (doesn't contain http), return as-is
    if 'http' not in input_string:
        return input_string

    # Extract file ID from document URL
    # https://docs.google.com/document/d/FILE_ID/edit
    match = re.search(r'/document/d/([a-zA-Z0-9_-]+)', input_string)
    if match:
        return match.group(1)

    # Extract file ID from spreadsheet URL
    # https://docs.google.com/spreadsheets/d/FILE_ID/edit
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', input_string)
    if match:
        return match.group(1)

    # Extract file ID from file URL
    # https://drive.google.com/file/d/FILE_ID/view
    match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', input_string)
    if match:
        return match.group(1)

    # Extract folder ID from folder URL
    # https://drive.google.com/drive/folders/FOLDER_ID
    match = re.search(r'/folders/([a-zA-Z0-9_-]+)', input_string)
    if match:
        return match.group(1)

    # Extract from open URL with ID parameter
    # https://drive.google.com/open?id=FILE_ID
    match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', input_string)
    if match:
        return match.group(1)

    # If no match, return original (might already be an ID)
    return input_string


def is_valid_drive_id(drive_id):
    """
    Check if a string looks like a valid Google Drive ID.

    Google Drive IDs are typically:
    - Alphanumeric with hyphens and underscores
    - Between 20-50 characters long

    Args:
        drive_id (str): String to check

    Returns:
        bool: True if it looks like a valid Drive ID
    """
    if not drive_id:
        return False

    # Must be alphanumeric with - and _
    if not re.match(r'^[a-zA-Z0-9_-]+$', drive_id):
        return False

    # Typical length range
    if len(drive_id) < 15 or len(drive_id) > 100:
        return False

    return True


def normalize_drive_input(input_string):
    """
    Normalize Drive input by extracting ID and validating.

    Args:
        input_string (str): URL or ID

    Returns:
        str: Extracted and validated ID

    Raises:
        ValueError: If input is invalid or ID cannot be extracted
    """
    if not input_string:
        raise ValueError("Drive ID or URL is required")

    # Extract ID from URL if needed
    drive_id = extract_drive_id(input_string)

    # Validate
    if not is_valid_drive_id(drive_id):
        raise ValueError(f"Invalid Google Drive ID or URL: {input_string}")

    return drive_id
