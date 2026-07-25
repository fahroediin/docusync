# 📄 DocuSync — Document Management System

DocuSync adalah sistem manajemen dokumen otomatis yang terintegrasi dengan **Google Drive**, **Elasticsearch** (pencarian full-text), **SQLite** (storage metadata), dan **WhatsApp Bot** (`whatsapp-web.js`).

---

## 🌟 Fitur Utama

1. **Auto Upload Google Drive & Direct Media Decryption**: Setiap dokumen (PDF, Word, Excel, dll) yang dikirim via WhatsApp pribadi maupun grup akan diunduh dan diunggah otomatis ke Google Drive tanpa mengalami Puppeteer context crash (`r`).
2. **Indeks Link Google Docs / Sheets / Drive**: Jika anggota grup membagikan link Google Docs/Sheets/Drive, bot otomatis mengecek dan mengambil judul dokumen tanpa perlu mengunggah file ulang.
3. **Pengamanan Duplikasi Dokumen & Link**: Mencegah pengunggahan ulang ke Google Drive jika file (berdasarkan nama & ukuran) atau link sudah pernah tersimpan sebelumnya.
4. **Hapus Dokumen Khusus Admin (`!hapus`)**: Fitur penghapusan dari Google Drive, Elasticsearch, dan SQLite yang **hanya dapat dilakukan oleh Admin** yang terdaftar di `.env` (dilengkapi pilihan angka `1`, `2`, `3`... jika terdapat banyak file mirip).
5. **Full-Text Search (Elasticsearch & SQLite Fallback)**: Pencarian dokumen instan berbasis judul, deskripsi, tag, dan pengunggah dengan SQLite LIKE search fallback jika Elasticsearch offline.
6. **Batas Ukuran & Format File**: Batas maksimum ukuran file (`MAX_UPLOAD_SIZE_MB=50`) dan format file yang diizinkan (`pdf`, `xls`, `xlsx`, `doc`, `docx`) yang dapat dikonfigurasi.

---

## 📋 Interactive WhatsApp Commands

- `!cari <kata kunci>` : Cari dokumen berdasarkan judul/metadata.
- `!list` / `!daftar` : Tampilkan 5 dokumen terbaru.
- `!hapus <nama/ID>` : (Admin Only) Hapus dokumen dari SQLite, Elasticsearch & Google Drive.
- `!status` : Cek kesehatan server API, Google Drive, & Elasticsearch.
- `!groupid` : Tampilkan ID grup WhatsApp.
- `!help` / `!bantuan` : Panduan penggunaan bot.

---

## 📁 Arsitektur Proyek

```
docusync/
├── app/
│   ├── main.py                    # Aplikasi utama FastAPI
│   ├── config.py                  # Konfigurasi environment
│   ├── database.py                # Koneksi & inisialisasi SQLite
│   ├── models/
│   │   └── document.py            # Schema Pydantic & WhatsApp payloads
│   ├── routers/
│   │   └── documents.py           # REST API routes (/upload, /send/media, /link/save, /search, /list, /delete)
│   └── services/
│       ├── gdrive_service.py      # Google Drive API v3 Service (OAuth & Service Account)
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

## 🚀 Cara Install & Menjalankan (Lokal / Windows)

### 1. Setup Environment Variables

Salin `.env.example` menjadi `.env`:

```bash
cp .env.example .env
```

Sesuaikan konfigurasi pada file `.env` menggunakan data dari template `.env.example`:

```env
GDRIVE_FOLDER_ID=your_gdrive_folder_id_here
ALLOWED_FILE_EXTENSIONS=pdf,xls,xlsx,doc,docx
MAX_UPLOAD_SIZE_MB=50
ADMIN_PHONE_NUMBERS=6281234567890
```

### 2. Autentikasi Google Drive (OAuth 2.0 User / Service Account)

Untuk menghindari kendala kuota penyimpanan Google Service Account (0-byte limit), gunakan OAuth 2.0 User Account:

```bash
python generate_token.py
```
*Script ini akan memicu login browser Google Drive Anda dan menghasilkan file `token.json`.*

### 3. Install Dependencies Python & Jalankan Server FastAPI

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# atau: venv\Scripts\activate  # Windows

pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

- **Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

### 4. Install & Jalankan Bot WhatsApp

Buka terminal baru:

```bash
cd bot
npm install
npm start
```

Scan QR code di terminal menggunakan aplikasi WhatsApp.

---

## 🌐 Deploy Step-by-Step ke AlmaLinux (9 / 8)

Berikut adalah panduan lengkap deployment sistem DocuSync pada server **AlmaLinux**:

### Step 1: Update & Install System Dependencies
Jalankan command berikut untuk menginstal Python, Node.js, Git, dan pustaka pendukung Chromium headless (Puppeteer):

```bash
sudo dnf update -y
sudo dnf install -y git python3 python3-pip nodejs npm epel-release

# Install Chromium & pustaka grafis pendukung Puppeteer
sudo dnf install -y chromium alsa-lib atk cups-libs gtk3 libXcomposite libXcursor libXdamage \
  libXext libXfixes libXi libXrandr libXrender libXtst pango at-spi2-atk libdrm libxcb mesa-libgbm nss nss-util
```

### Step 2: Clone Repository & Virtual Environment
```bash
cd /opt
sudo git clone https://github.com/Username/docusync.git
sudo chown -R $USER:$USER /opt/docusync
cd /opt/docusync

# Membuat Python Virtual Environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Install Bot Dependencies & PM2 Process Manager
```bash
cd /opt/docusync/bot
npm install
sudo npm install -g pm2
```

### Step 4: Setup Configuration & Credentials
```bash
cd /opt/docusync
cp .env.example .env
```
Sunting file `.env` (misal dengan `nano .env`) dan pastikan mengatur:
- `GDRIVE_FOLDER_ID`
- `ADMIN_PHONE_NUMBERS` (Nomor HP / LID Admin yang berhak menghapus)
- Unggah file `credentials.json` dan/atau `token.json` ke folder `/opt/docusync/`.

### Step 5: Jalankan Layanan dengan PM2

```bash
# 1. Jalankan Backend Server FastAPI
cd /opt/docusync
pm2 start "venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000" --name "docusync-api"

# 2. Jalankan Bot WhatsApp
cd /opt/docusync/bot
pm2 start bot.js --name "docusync-bot"

# 3. Simpan state PM2 agar otomatis berjalan saat server restart / reboot
pm2 save
sudo env PATH=$PATH:/usr/bin pm2 startup systemd -u $USER --hp /home/$USER
```

### Step 6: Log Verification & Monitoring
```bash
# Cek status layanan
pm2 status

# Cek log secara realtime
pm2 logs docusync-api
pm2 logs docusync-bot
```

---

## 🔒 Keamanan & Praktik Terbaik

- File `token.json` dan `credentials.json` berisi kredensial sensitif. Pastikan file ini masuk ke dalam `.gitignore` dan jangan pernah dipublikasikan ke repository publik.
- Hak akses `!hapus` secara ketat dijaga oleh middleware `isSenderAdmin()`. Pastikan variabel `ADMIN_PHONE_NUMBERS` pada file `.env` diisi dengan benar.

