import os
import logging
from typing import Dict, Any, Optional
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive'
]


class GDriveService:
    def __init__(self):
        self.service = None
        self.folder_id = settings.GDRIVE_FOLDER_ID
        self.credentials_path = settings.GDRIVE_CREDENTIALS_PATH
        self.token_path = "token.json"
        self._init_service()

    def _init_service(self):
        creds = None

        # 1. Prefer OAuth 2.0 User Token (token.json) for personal Gmail accounts
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                self.service = build('drive', 'v3', credentials=creds)
                logger.info("Google Drive service initialized using OAuth2 User Credentials (token.json).")
                return
            except Exception as e:
                logger.warning(f"Failed to load token.json, falling back to credentials.json: {str(e)}")

        # 2. Fallback to Service Account (credentials.json)
        if not os.path.exists(self.credentials_path):
            logger.warning(f"Google Drive credentials file not found at: {self.credentials_path}")
            return

        try:
            creds = service_account.Credentials.from_service_account_file(
                self.credentials_path, scopes=SCOPES
            )
            self.service = build('drive', 'v3', credentials=creds)
            logger.info("Google Drive service successfully initialized using Service Account.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Drive service: {str(e)}")

    def is_configured(self) -> bool:
        return self.service is not None and bool(self.folder_id)

    async def upload_file(
        self, file_path: str, filename: str, mimetype: str
    ) -> Dict[str, Any]:
        # Always reload folder_id from settings in case .env was updated
        self.folder_id = settings.GDRIVE_FOLDER_ID or self.folder_id

        if not self.service:
            self._init_service()
            if not self.service:
                raise RuntimeError(
                    "Google Drive service belum terkonfigurasi. "
                    "Harap sediakan credentials.json atau jalankan 'python generate_token.py'."
                )

        if not self.folder_id or not self.folder_id.strip():
            raise RuntimeError(
                "GDRIVE_FOLDER_ID belum diisi di file .env! "
                "Harap isi GDRIVE_FOLDER_ID pada file .env."
            )

        file_metadata = {
            'name': filename,
            'parents': [self.folder_id.strip()]
        }

        is_resumable = os.path.exists(file_path) and os.path.getsize(file_path) > 5 * 1024 * 1024
        media = MediaFileUpload(file_path, mimetype=mimetype, resumable=is_resumable)

        for attempt in range(1, 4):
            try:
                file = self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, name, webViewLink, webContentLink',
                    supportsAllDrives=True
                ).execute(num_retries=3)

                file_id = file.get('id')

                # Set public read permission ("anyone with link")
                try:
                    self.service.permissions().create(
                        fileId=file_id,
                        body={'type': 'anyone', 'role': 'reader'},
                        fields='id',
                        supportsAllDrives=True
                    ).execute(num_retries=3)
                except Exception as perm_err:
                    logger.warning(f"Failed to set public permission on GDrive file {file_id}: {str(perm_err)}")

                web_link = file.get('webViewLink') or f"https://drive.google.com/file/d/{file_id}/view"

                return {
                    'file_id': file_id,
                    'web_view_link': web_link,
                    'download_link': file.get('webContentLink'),
                }
            except Exception as e:
                err_msg = str(e)
                if attempt < 3 and ('_ssl' in err_msg or 'EOF' in err_msg or 'protocol' in err_msg or 'socket' in err_msg):
                    logger.warning(f"SSL connection drop to Google Drive (attempt {attempt}/3). Re-initializing service...")
                    self._init_service()
                    media = MediaFileUpload(file_path, mimetype=mimetype, resumable=is_resumable)
                    continue
                logger.error(f"Error uploading file to Google Drive: {str(e)}")
                raise e

    async def delete_file(self, file_id: str) -> bool:
        if not self.service:
            self._init_service()
            if not self.service:
                return False

        try:
            self.service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            logger.info(f"Deleted file {file_id} from Google Drive.")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file {file_id} from Google Drive: {str(e)}")
            return False

    @staticmethod
    def extract_file_id_from_url(url: str) -> Optional[str]:
        import re
        patterns = [
            r'/d/([a-zA-Z0-9_-]+)',
            r'/folders/([a-zA-Z0-9_-]+)',
            r'[?&]id=([a-zA-Z0-9_-]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        if not self.service:
            self._init_service()
            if not self.service:
                return None

        try:
            file_meta = self.service.files().get(
                fileId=file_id,
                fields='id, name, mimeType, description, trashed',
                supportsAllDrives=True
            ).execute()
            return file_meta
        except Exception as e:
            logger.warning(f"Could not fetch GDrive file info for ID {file_id}: {str(e)}")
            return None

    async def check_file_exists(self, file_id: str) -> bool:
        if not self.service:
            self._init_service()
            if not self.service:
                return True  # Default to True if GDrive service unavailable

        try:
            file_meta = self.service.files().get(
                fileId=file_id,
                fields='id, trashed',
                supportsAllDrives=True
            ).execute()
            if file_meta and not file_meta.get('trashed', False):
                return True
            return False
        except Exception as e:
            logger.info(f"File {file_id} does not exist on Google Drive: {str(e)}")
            return False

    async def list_folder_files(
        self, folder_id: str, mime_filter: str = "application/pdf"
    ) -> list:
        """
        List all files in a Google Drive folder, optionally filtered by MIME type.

        Args:
            folder_id: The Google Drive folder ID to list files from.
            mime_filter: MIME type to filter (default: PDF). Use None for all files.

        Returns:
            List of file metadata dicts: {id, name, mimeType, size, createdTime, webViewLink}
        """
        if not self.service:
            self._init_service()
            if not self.service:
                raise RuntimeError(
                    "Google Drive service belum terkonfigurasi. "
                    "Harap sediakan credentials.json atau jalankan 'python generate_token.py'."
                )

        query = f"'{folder_id}' in parents and trashed = false"
        if mime_filter:
            query += f" and mimeType = '{mime_filter}'"

        try:
            all_files = []
            page_token = None

            while True:
                response = self.service.files().list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType, size, createdTime, webViewLink)",
                    orderBy="name",
                    pageSize=100,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageToken=page_token
                ).execute()

                files = response.get("files", [])
                all_files.extend(files)

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            logger.info(f"Listed {len(all_files)} files from GDrive folder {folder_id}")
            return all_files

        except Exception as e:
            logger.error(f"Failed to list files from GDrive folder {folder_id}: {str(e)}")
            raise RuntimeError(f"Gagal membaca daftar file dari Google Drive: {str(e)}")

    async def download_file(self, file_id: str, dest_path: str) -> str:
        """
        Download a file from Google Drive to a local path.

        Args:
            file_id: The Google Drive file ID to download.
            dest_path: Local file path to save the downloaded file.

        Returns:
            The destination file path.
        """
        if not self.service:
            self._init_service()
            if not self.service:
                raise RuntimeError(
                    "Google Drive service belum terkonfigurasi. "
                    "Harap sediakan credentials.json atau jalankan 'python generate_token.py'."
                )

        import io
        from googleapiclient.http import MediaIoBaseDownload

        try:
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            request = self.service.files().get_media(fileId=file_id)
            with open(dest_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            file_size = os.path.getsize(dest_path)
            logger.info(f"Downloaded GDrive file {file_id} to {dest_path} ({file_size} bytes)")
            return dest_path

        except Exception as e:
            logger.error(f"Failed to download GDrive file {file_id}: {str(e)}")
            # Cleanup partial download
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise RuntimeError(f"Gagal mengunduh file dari Google Drive: {str(e)}")

    async def export_spreadsheet_csv(self, spreadsheet_id: str) -> str:
        """
        Export a Google Spreadsheet as CSV text.
        Works seamlessly via Drive API export.

        Args:
            spreadsheet_id: The Google Spreadsheet file ID.

        Returns:
            CSV content as string.
        """
        if not self.service:
            self._init_service()
            if not self.service:
                raise RuntimeError(
                    "Google Drive service belum terkonfigurasi. "
                    "Harap sediakan credentials.json atau jalankan 'python generate_token.py'."
                )

        try:
            content_bytes = self.service.files().export(
                fileId=spreadsheet_id,
                mimeType='text/csv'
            ).execute()

            if isinstance(content_bytes, bytes):
                return content_bytes.decode('utf-8-sig', errors='replace')
            return str(content_bytes)

        except Exception as e:
            logger.error(f"Failed to export spreadsheet {spreadsheet_id} as CSV: {str(e)}")
            raise RuntimeError(f"Gagal membaca Google Spreadsheet dari Google Drive: {str(e)}")


gdrive_service = GDriveService()
