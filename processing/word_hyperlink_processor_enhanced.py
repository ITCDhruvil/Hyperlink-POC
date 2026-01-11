"""
Enhanced Word Document Hyperlink Processor with Path Support
Users can provide paths like "2025/December/Carl_Mayfield" instead of folder IDs
"""
from typing import Dict, Optional
from .word_hyperlink_processor import WordHyperlinkProcessor
from .drive_path_resolver import DrivePathResolver, StandardDriveStructure


class WordHyperlinkProcessorEnhanced(WordHyperlinkProcessor):
    """
    Enhanced processor that accepts Drive paths instead of just IDs
    """

    def __init__(self):
        super().__init__()
        self.path_resolver = DrivePathResolver()
        self.structure = StandardDriveStructure()

    def process_with_path(
        self,
        drive_folder_path: str,
        word_file_id: str,
        output_folder_path: Optional[str] = None,
        temp_dir: str = '/tmp'
    ) -> Dict:
        """
        Process Word document using Drive folder PATH instead of ID

        Args:
            drive_folder_path: Path like "2025/December/Carl_Mayfield/splits"
            word_file_id: Google Drive file ID of Word document
            output_folder_path: Optional output folder path (defaults to input path)
            temp_dir: Temporary directory

        Returns:
            Processing results dict

        Example:
            >>> processor = WordHyperlinkProcessorEnhanced()
            >>> result = processor.process_with_path(
            ...     drive_folder_path="2025/December/Carl_Mayfield/splits",
            ...     word_file_id="1XYZ789..."
            ... )
        """
        # Resolve paths to IDs
        drive_folder_id = self.path_resolver.resolve_path(drive_folder_path)

        if not drive_folder_id:
            raise Exception(f"Folder not found: {drive_folder_path}")

        if output_folder_path:
            output_folder_id = self.path_resolver.resolve_path(
                output_folder_path,
                create_if_missing=True
            )
        else:
            output_folder_id = drive_folder_id

        # Use base class method with resolved IDs
        return self.process_from_drive_folder(
            drive_folder_id=drive_folder_id,
            word_file_id=word_file_id,
            output_folder_id=output_folder_id,
            temp_dir=temp_dir
        )

    def process_patient_document(
        self,
        patient_name: str,
        word_file_id: str,
        year: Optional[str] = None,
        month: Optional[str] = None,
        temp_dir: str = '/tmp'
    ) -> Dict:
        """
        Process Word document for a patient using standard folder structure

        Automatically finds: {year}/{month}/{patient_name}/splits

        Args:
            patient_name: Patient name (e.g., "Carl_Mayfield")
            word_file_id: Google Drive file ID of Word document
            year: Year (defaults to current year)
            month: Month name (defaults to current month)
            temp_dir: Temporary directory

        Returns:
            Processing results dict

        Example:
            >>> processor = WordHyperlinkProcessorEnhanced()
            >>> result = processor.process_patient_document(
            ...     patient_name="Carl_Mayfield",
            ...     word_file_id="1XYZ789...",
            ...     year="2025",
            ...     month="December"
            ... )
        """
        # Use current year/month if not provided
        if not year or not month:
            from datetime import datetime
            year = year or str(datetime.now().year)
            month = month or datetime.now().strftime('%B')

        # Get splits folder ID
        splits_folder_id = self.structure.get_splits_folder(
            year, month, patient_name, create=False
        )

        if not splits_folder_id:
            raise Exception(
                f"Patient folder not found: {year}/{month}/{patient_name}/splits"
            )

        # Get patient folder for output
        patient_folder_id = self.structure.get_patient_folder(
            year, month, patient_name
        )

        # Process
        return self.process_from_drive_folder(
            drive_folder_id=splits_folder_id,
            word_file_id=word_file_id,
            output_folder_id=patient_folder_id,
            temp_dir=temp_dir
        )

    def process_patient_document_auto(
        self,
        patient_name: str,
        word_file_id: str,
        temp_dir: str = '/tmp'
    ) -> Dict:
        """
        Automatically find and process patient document

        Searches for patient folder in current year/month

        Args:
            patient_name: Patient name
            word_file_id: Word document file ID
            temp_dir: Temporary directory

        Returns:
            Processing results dict

        Example:
            >>> processor = WordHyperlinkProcessorEnhanced()
            >>> # Automatically finds "2025/December/Carl_Mayfield"
            >>> result = processor.process_patient_document_auto(
            ...     patient_name="Carl_Mayfield",
            ...     word_file_id="1XYZ789..."
            ... )
        """
        # Search for patient folder
        patient_data = self.structure.resolve_patient_path(patient_name)

        if not patient_data:
            raise Exception(f"Patient folder not found for: {patient_name}")

        # Process
        return self.process_from_drive_folder(
            drive_folder_id=patient_data['splits_folder_id'],
            word_file_id=word_file_id,
            output_folder_id=patient_data['patient_folder_id'],
            temp_dir=temp_dir
        )
