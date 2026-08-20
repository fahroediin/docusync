# DocuSync — Document Management System

DocuSync adalah sistem manajemen dokumen otomatis yang terintegrasi dengan Google Drive, Elasticsearch (pencarian full-text), SQLite (storage metadata), Google Sheets (sinkronisasi profiling), dan WhatsApp Bot (whatsapp-web.js).

---

## Fitur Utama

1. **Auto Upload Google Drive & Direct Media Decryption**: Setiap dokumen (PDF, Word, Excel, dll) yang dikirim via WhatsApp pribadi maupun grup akan diunduh dan diunggah otomatis ke Google Drive.
2. **Indeks Link Google Docs / Sheets / Drive**: Jika anggota grup membagikan link Google Docs/Sheets/Drive, bot otomatis mengecek dan mengambil judul dokumen tanpa perlu mengunggah file ulang.
3. **Katalog PDF Google Drive (`!daftar-pdf`)**: Menampilkan daftar file PDF dari folder Google Drive khusus dengan format penamaan terstandarisasi (`Nama Perusahaan_DD-Bulan-YYYY.pdf`).
4. **Profiling Perusahaan via Google Sheets (`!profiling`)**: Menampilkan profil lengkap, kategori, tanggal dokumen, PIC, dan ringkasan perusahaan secara instan dari database yang tersinkronisasi dengan Google Spreadsheet.
5. **Sinkronisasi Spreadsheet (`!sync-sheet`)**: Fitur khusus Admin untuk menarik dan memperbarui data profiling dari Google Spreadsheet ke database SQLite lokal secara realtime.
6. **Pengamanan Duplikasi Dokumen & Link**: Mencegah pengunggahan ulang ke Google Drive jika file (berdasarkan nama dan ukuran) atau link sudah pernah tersimpan sebelumnya.
7. **Hapus Dokumen Khusus Admin (`!hapus`)**: Fitur penghapusan dari Google Drive, Elasticsearch, dan SQLite yang hanya dapat dilakukan oleh Admin yang terdaftar di konfigurasi environment.
8. **Full-Text Search (Elasticsearch & SQLite Fallback)**: Pencarian dokumen instan berbasis judul, deskripsi, tag, dan pengunggah dengan fallback pencarian SQLite LIKE jika Elasticsearch offline.
9. **Batas Ukuran & Format File**: Batas maksimum ukuran file (`MAX_UPLOAD_SIZE_MB=50`) dan format file yang diizinkan (`pdf`, `xls`, `xlsx`, `doc`, `docx`) dapat dikonfigurasi.

---

## Interactive WhatsApp Commands

### Manajemen Dokumen
- `!cari <kata kunci>` : Cari dokumen berdasarkan judul/metadata.
- `!list` / `!daftar` : Tampilkan 5 dokumen terbaru yang tersimpan.
- `!hapus <nama/ID>` : (Admin Only) Hapus dokumen dari SQLite, Elasticsearch & Google Drive.
- `!sync` : (Admin Only) Sinkronisasi dan bersihkan dokumen yang telah dihapus di Google Drive.

### Katalog PDF & Informasi
- `!daftar-pdf` / `!pdf` : Tampilkan daftar seluruh file PDF di folder katalog Google Drive.
- `!info <nama perusahaan>` : Cari dan tampilkan informasi perusahaan dari database.
- `!info <nomor>` : Tampilkan informasi perusahaan berdasarkan nomor urut dari hasil `!daftar-pdf`.
- `!sync-sheet` : (Admin Only) Sinkronisasi data profil dari Google Spreadsheet ke database.

### Sistem & Informasi
- `!status` : Cek status backend API, Google Drive API, dan Elasticsearch.
- `!groupid` : Tampilkan ID grup WhatsApp saat ini.
- `!help` / `!bantuan` : Panduan penggunaan seluruh command bot.

---

## Arsitektur Proyek

```
docusync/
├── app/
│   ├── main.py                    # Aplikasi utama FastAPI & routing
│   ├── config.py                  # Konfigurasi Pydantic & environment settings
│   ├── database.py                # Inisialisasi SQLite (documents & company_profiles)
│   ├── models/
│   │   ├── document.py            # Schema Pydantic dokumen & WhatsApp payload
│   │   └── profiling.py           # Schema Pydantic katalog PDF & profiling
│   ├── routers/
│   │   ├── documents.py           # REST API routes dokumen (/upload, /search, /list, /delete, dll)
│   │   └── profiling.py           # REST API routes profiling (/pdfs, /search, /all, /sync)
│   └── services/
│       ├── gdrive_service.py      # Google Drive API v3 Service (OAuth & Service Account)
│       ├── sheets_service.py      # Google Sheets Profiling Sync & Lookup Service
│       ├── wa_decrypt_service.py  # WhatsApp CDN AES-256 HKDF Media Decryptor
│       ├── search_service.py      # Elasticsearch async indexing & search
│       └── database_service.py    # SQLite CRUD, duplicate check & fallback search
├── bot/
│   ├── bot.js                     # WhatsApp Bot client (whatsapp-web.js)
│   └── package.json
├── storage/                       # Database SQLite & temp directory
├── generate_token.py              # Script pembuatan token OAuth 2.0 User (token.json)
├── docker-compose.yml             # Elasticsearch local development setup
├── requirements.txt               # Dependencies Python
├── .env.example                   # Template konfigurasi environment
└── README.md
```

---

## Cara Install & Menjalankan (Lokal / Development)

### 1. Setup Environment Variables

Salin file `.env.example` menjadi `.env`:

```bash
cp .env.example .env
```

Sesuaikan variabel konfigurasi pada file `.env`:

```env
GDRIVE_FOLDER_ID=your_gdrive_folder_id_here
GDRIVE_SUMMARY_FOLDER_ID=your_pdf_catalog_folder_id_here
PROFILING_SPREADSHEET_ID=your_google_spreadsheet_id_here
ALLOWED_FILE_EXTENSIONS=pdf,xls,xlsx,doc,docx
MAX_UPLOAD_SIZE_MB=50
ADMIN_PHONE_NUMBERS=6281234567890
```

### 2. Autentikasi Google Drive & Sheets

Untuk menghindari batasan kuota Google Service Account, gunakan OAuth 2.0 User Account:

```bash
python generate_token.py
```
*Script akan membuka browser untuk login Google dan membuat file `token.json`.*

### 3. Install Dependencies Python & Jalankan Server FastAPI

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# atau: venv\Scripts\activate  # Windows

pip install -r requirements.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Swagger API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/v1/health

### 4. Install & Jalankan Bot WhatsApp

Buka terminal baru:

```bash
cd bot
npm install
npm start
```

Pindai (scan) QR code di terminal menggunakan aplikasi WhatsApp.

---

## Deploy ke Server / Cloud VM (GCP Compute Engine / Linux)

### Step 1: Update System & Install Dependencies

```bash
sudo apt update -y && sudo apt upgrade -y  # Ubuntu / Debian
# atau: sudo dnf update -y                 # AlmaLinux / RHEL

# Install Git, Python, Node.js, and Chromium headless dependencies
sudo apt install -y git python3 python3-pip python3-venv nodejs npm \
  chromium-browser libasound2 libatk1.0-0 libc6 libcairo2 libcups2 \
  libdbus-1-3 libexpat1 libfontconfig1 libgbm1 libgcc1 libgdk-pixbuf2.0-0 \
  libglib2.0-0 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 libpangocairo-1.0-0 \
  libstdc++6 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
  libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 libxtst6
```

### Step 2: Clone Repository & Virtual Environment

```bash
git clone https://github.com/Username/docusync.git
cd docusync

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Install Bot Dependencies & PM2

```bash
cd bot
npm install
sudo npm install -g pm2
cd ..
```

### Step 4: Setup Environment & Credentials

```bash
cp .env.example .env
nano .env
```
Pastikan file `token.json` dan/atau `credentials.json` sudah berada di direktori root `docusync/`.

### Step 5: Jalankan Layanan dengan PM2

```bash
# 1. Jalankan Backend Server FastAPI
pm2 start "venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000" --name "docusync-api"

# 2. Jalankan Bot WhatsApp
cd bot
pm2 start bot.js --name "docusync-bot"
cd ..

# 3. Simpan state PM2 agar otomatis berjalan saat server restart
pm2 save
pm2 startup
```

### Step 6: Monitoring & Log

```bash
# Cek status layanan
pm2 status

# Cek log secara realtime
pm2 logs docusync-api
pm2 logs docusync-bot
```

---

## Keamanan & Konfigurasi Akses

- File `token.json`, `credentials.json`, `oauth_client.json`, dan `.env` berisi kredensial sensitif. Pastikan seluruh file ini terdaftar di `.gitignore` dan tidak pernah dipublikasikan ke repository publik.
- Hak akses perintah administratif (`!hapus`, `!sync`, `!sync-sheet`) secara ketat diverifikasi melalui fungsi `isSenderAdmin()`. Pastikan nomor telepon admin pada variabel `ADMIN_PHONE_NUMBERS` di file `.env` sudah sesuai.
