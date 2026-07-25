"""
Script pembantu untuk menghasilkan token.json (OAuth 2.0 User Token) untuk Google Drive API.
Gunakan jika Anda menggunakan akun Google pribadi (@gmail.com).

Langkah:
1. Buat 'OAuth 2.0 Client ID' (Desktop App) di Google Cloud Console.
2. Download file JSON-nya dan simpan sebagai 'oauth_client.json' di folder proyek ini.
3. Jalankan script ini: `python generate_token.py`
4. Login via browser dengan akun Google Anda (Geeky.Last@gmail.com).
5. Script akan menghasilkan file 'token.json'.
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive'
]

CLIENT_SECRET_FILE = 'oauth_client.json'
TOKEN_FILE = 'token.json'


def main():
    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"❌ File '{CLIENT_SECRET_FILE}' tidak ditemukan!")
        print("\nPetunjuk:")
        print("1. Buka Google Cloud Console: https://console.cloud.google.com/apis/credentials")
        print("2. Klik 'Create Credentials' -> 'OAuth client ID'")
        print("3. Pilih Application type: 'Desktop app', beri nama, lalu klik 'Create'")
        print("4. Download JSON-nya dan rename menjadi 'oauth_client.json' di folder proyek ini.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())

    print(f"✅ Berhasil! File '{TOKEN_FILE}' telah dibuat.")
    print("Sistem DocuSync sekarang akan mengunggah file langsung ke Google Drive pribadi Anda tanpa masalah kuota!")


if __name__ == '__main__':
    main()
