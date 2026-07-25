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

        media = MediaFileUpload(file_path, mimetype=mimetype, resumable=True)

        try:
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink, webContentLink',
                supportsAllDrives=True
            ).execute()

            file_id = file.get('id')

            # Set public read permission ("anyone with link")
            try:
                self.service.permissions().create(
                    fileId=file_id,
                    body={'type': 'anyone', 'role': 'reader'},
                    fields='id',
                    supportsAllDrives=True
                ).execute()
            except Exception as perm_err:
                logger.warning(f"Failed to set public permission on GDrive file {file_id}: {str(perm_err)}")

            web_link = file.get('webViewLink') or f"https://drive.google.com/file/d/{file_id}/view"

            return {
                'file_id': file_id,
                'web_view_link': web_link,
                'download_link': file.get('webContentLink'),
            }
        except Exception as e:
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


gdrive_service = GDriveService()


