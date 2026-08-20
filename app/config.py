import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "DocuSync - Document Management System"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # Google Drive Settings
    GDRIVE_FOLDER_ID: str = ""
    GDRIVE_CREDENTIALS_PATH: str = "credentials.json"

    # Elasticsearch Settings
    ELASTICSEARCH_URL: str = "http://localhost:9200"
    ELASTICSEARCH_INDEX: str = "docusync-documents"
    ELASTICSEARCH_API_KEY: str = ""

    # SQLite Settings
    SQLITE_DB_PATH: str = "storage/docusync.db"
    
    # Upload & File Filter Settings
    MAX_UPLOAD_SIZE_MB: int = 50
    TEMP_STORAGE_DIR: str = "storage/temp"
    ALLOWED_FILE_EXTENSIONS: str = "pdf,xls,xlsx,doc,docx"

    # Profiling & PDF Catalog Settings
    GDRIVE_SUMMARY_FOLDER_ID: str = ""
    PROFILING_SPREADSHEET_ID: str = ""

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [ext.strip().lower().lstrip('.') for ext in self.ALLOWED_FILE_EXTENSIONS.split(',') if ext.strip()]


    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
