const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const fs = require('fs');
const path = require('path');
const FormData = require('form-data');

// Global error handlers — prevent Node.js crash
process.on('unhandledRejection', (reason) => {
    console.error('[docusync-bot] Unhandled Rejection (ignored):', reason?.message || String(reason));
});
process.on('uncaughtException', (err) => {
    console.error('[docusync-bot] Uncaught Exception (ignored):', err.message);
});

// Load environment variables from root .env file
const envPath = path.join(__dirname, '../.env');
if (fs.existsSync(envPath)) {
    try {
        const envContent = fs.readFileSync(envPath, 'utf8');
        envContent.split(/\r?\n/).forEach(line => {
            const trimmed = line.trim();
            if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
                const [key, ...valParts] = trimmed.split('=');
                const k = key.trim();
                const v = valParts.join('=').trim().replace(/^["']|["']$/g, '');
                if (k) process.env[k] = v;
            }
        });
    } catch (_) {}
}

// ─────────────────────────────────────────────────────────────
// DocuSync — WhatsApp Bot Client (whatsapp-web.js)
// ─────────────────────────────────────────────────────────────

const DOCUSYNC_BASE_URL = process.env.DOCUSYNC_BASE_URL || 'http://127.0.0.1:8000';
const DOCUSYNC_HEALTH_URL = `${DOCUSYNC_BASE_URL}/api/v1/health`;
const DOCUSYNC_UPLOAD_URL = `${DOCUSYNC_BASE_URL}/api/v1/upload`;
const DOCUSYNC_SEND_MEDIA_URL = `${DOCUSYNC_BASE_URL}/api/v1/send/media`;
const DOCUSYNC_SAVE_LINK_URL = `${DOCUSYNC_BASE_URL}/api/v1/link/save`;
const DOCUSYNC_SEARCH_URL = `${DOCUSYNC_BASE_URL}/api/v1/search`;
const DOCUSYNC_LIST_URL = `${DOCUSYNC_BASE_URL}/api/v1/documents`;

const CLIENT_ID = 'docusync-bot';

// Timestamp when bot becomes ready — ignore all messages before this
let botReadyTimestamp = 0;

// Group filtering settings from .env
const ALLOW_ALL_GROUPS = (process.env.ALLOW_ALL_GROUPS || 'true').toLowerCase() === 'true';
const ALLOWED_GROUP_IDS = (process.env.COMMA_SEPARATED_GROUP_IDS || '')
    .split(',').map(id => id.trim()).filter(Boolean);

// Upload size limit (in MB) from .env
const MAX_UPLOAD_SIZE_MB = parseInt(process.env.MAX_UPLOAD_SIZE_MB || '50', 10);
const MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024;

// Temp staging directory
const TEMP_DIR = path.resolve(__dirname, 'temp_downloads');
if (!fs.existsSync(TEMP_DIR)) {
    fs.mkdirSync(TEMP_DIR, { recursive: true });
}

// ─────────────────────────────────────────────────────────────
// Client Configuration (Resource-Optimized for VPS)
// ─────────────────────────────────────────────────────────────
process.on('uncaughtException', (error) => {
    if (error.message && error.message.includes('Execution context was destroyed')) {
        console.warn(`[${CLIENT_ID}] Ignored transient Puppeteer navigation error:`, error.message);
        return;
    }
    console.error(`[${CLIENT_ID}] Uncaught Exception:`, error.message);
});

process.on('unhandledRejection', (reason, promise) => {
    const reasonStr = String(reason?.message || reason || '');
    if (reasonStr.includes('Execution context was destroyed')) {
        console.warn(`[${CLIENT_ID}] Ignored transient Puppeteer navigation rejection.`);
        return;
    }
    console.error(`[${CLIENT_ID}] Unhandled Rejection:`, reasonStr);
});

const client = new Client({
    authStrategy: new LocalAuth({ clientId: CLIENT_ID }),
    puppeteer: {
        headless: true,
        protocolTimeout: 300000,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--disable-site-isolation-trials',
            '--disable-features=IsolateOrigins,site-per-process',
            '--no-first-run',
            '--disable-gpu',
            '--disable-infobars',
            '--window-position=0,0',
            '--window-size=1366,768',
            '--ignore-certificate-errors',
            '--ignore-ssl-errors',
            '--ignore-certificate-errors-spki-list'
        ],
        timeout: 90000,
        slowMo: 0
    }
});

// ─────────────────────────────────────────────────────────────
// Utility Functions
// ─────────────────────────────────────────────────────────────

function clearChromiumLocks() {
    const sessionDir = path.resolve('.wwebjs_auth', `session-${CLIENT_ID}`);
    if (!fs.existsSync(sessionDir)) return;
    for (const name of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
        try {
            fs.rmSync(path.join(sessionDir, name), { force: true });
        } catch (_) { }
    }
    try {
        const defaultDir = path.join(sessionDir, 'Default');
        if (fs.existsSync(defaultDir)) {
            for (const name of ['SingletonLock', 'SingletonCookie', 'SingletonSocket']) {
                fs.rmSync(path.join(defaultDir, name), { force: true });
            }
        }
    } catch (_) { }
}

function formatUploaderName(str) {
    if (!str) return '-';
    let clean = str.replace(/\s*\([\d\w@._-]+\)\s*$/, '').trim();
    clean = clean.replace(/@c\.us|@g\.us/gi, '').trim();
    return clean || str;
}

async function sendReply(message, text) {
    try {
        await message.reply(text);
        return;
    } catch (_) {}
    try {
        await client.sendMessage(message.from, text);
    } catch (err) {
        console.error(`[${CLIENT_ID}] Gagal mengirim balasan ke ${message.from}:`, err.message);
    }
}

function getAdminPhoneNumbers() {
    let rawEnv = process.env.ADMIN_PHONE_NUMBERS || '';
    if (fs.existsSync(envPath)) {
        try {
            const content = fs.readFileSync(envPath, 'utf8');
            const line = content.split(/\r?\n/).find(l => l.trim().startsWith('ADMIN_PHONE_NUMBERS='));
            if (line) {
                rawEnv = line.split('=').slice(1).join('=').trim().replace(/^["']|["']$/g, '');
            }
        } catch (_) {}
    }
    return rawEnv.split(',').map(n => n.trim().replace(/[^0-9]/g, '')).filter(Boolean);
}

/**
 * Checks if the sender is an authorized Admin.
 * Strictly checks against ADMIN_PHONE_NUMBERS in .env file.
 * Resolves phone numbers, WhatsApp LIDs, and contact details.
 */
async function isSenderAdmin(message) {
    const adminNums = getAdminPhoneNumbers();
    if (adminNums.length === 0) {
        console.log(`[${CLIENT_ID}] Access Denied for !hapus. ADMIN_PHONE_NUMBERS is empty in .env!`);
        return false;
    }

    const candidates = new Set();

    const rawAuthor = message.author || '';
    const rawFrom = message.from || '';

    if (rawAuthor) candidates.add(rawAuthor.replace(/[^0-9]/g, ''));
    if (rawFrom && !rawFrom.endsWith('@g.us')) candidates.add(rawFrom.replace(/[^0-9]/g, ''));

    if (message._data) {
        if (message._data.author) candidates.add(message._data.author.replace(/[^0-9]/g, ''));
        if (message._data.from && !message._data.from.endsWith('@g.us')) candidates.add(message._data.from.replace(/[^0-9]/g, ''));
        if (message._data.participant) candidates.add(message._data.participant.replace(/[^0-9]/g, ''));
    }

    try {
        const contact = await message.getContact();
        if (contact) {
            if (contact.number) candidates.add(contact.number.replace(/[^0-9]/g, ''));
            if (contact.id && contact.id.user) candidates.add(contact.id.user.replace(/[^0-9]/g, ''));
        }
    } catch (_) {}

    const candidateArr = Array.from(candidates).filter(Boolean);

    for (const cand of candidateArr) {
        const matched = adminNums.some(adminNum => {
            if (!adminNum) return false;
            return cand === adminNum || cand.endsWith(adminNum) || adminNum.endsWith(cand);
        });
        if (matched) return true;
    }

    console.log(`[${CLIENT_ID}] Access Denied for !hapus. Sender Candidate IDs: [${candidateArr.join(', ')}]. Configured Admin Numbers in .env: [${adminNums.join(', ')}]`);
    return false;
}

async function checkDocuSyncServer() {
    try {
        const res = await axios.get(DOCUSYNC_HEALTH_URL, { timeout: 5000 });
        if (res.data && res.data.status === 'online') {
            console.log(`[${CLIENT_ID}] DocuSync API Engine ONLINE (${DOCUSYNC_BASE_URL})`);
            return res.data;
        }
    } catch (_) {
        console.log(`[${CLIENT_ID}] DocuSync API Engine OFFLINE — jalankan: uvicorn app.main:app --reload --port 8000`);
        return null;
    }
}

/**
 * Extract media metadata from whatsapp-web.js message object.
 * Extracts sender name cleanly without phone number / ID.
 */
function extractMediaMeta(message) {
    const raw = message._data || {};
    const isGroup = message.from.endsWith('@g.us');
    
    // Extract clean name only (no phone number or internal IDs)
    const rawName = raw.notifyName || raw.pushname || message.author?.split('@')[0] || message.from.split('@')[0] || 'User';
    const uploader = formatUploaderName(rawName);
    const chatSource = isGroup ? `Group: ${message.from}` : `Private: ${uploader}`;
    const filename = (raw.filename || message.body || '').trim().replace(/[\/\\]/g, '_');

    return {
        directPath: raw.directPath || null,
        url: raw.deprecatedMms3Url || raw.url || null,
        mediaKey: raw.mediaKey || null,
        mimetype: raw.mimetype || 'application/pdf',
        mediaType: message.type || 'document',
        filename: filename,
        title: filename,
        uploader: uploader,
        chat_source: chatSource,
        description: message.body && message.body !== filename ? message.body : null
    };
}

/**
 * Send media metadata directly to DocuSync /send/media endpoint.
 * Server downloads & decrypts from WhatsApp CDN directly.
 */
async function sendMediaToServer(message) {
    const meta = extractMediaMeta(message);
    if (!meta.mediaKey || (!meta.directPath && !meta.url)) {
        throw new Error('Metadata media WhatsApp tidak lengkap.');
    }

    console.log(`[${CLIENT_ID}] Direct /send/media: Mengirim metadata file "${meta.filename || meta.mimetype}" ke DocuSync server...`);
    const res = await axios.post(DOCUSYNC_SEND_MEDIA_URL, meta, { timeout: 120000 });
    return res.data;
}

// ─────────────────────────────────────────────────────────────
// Bulk Media Queue Manager
// ─────────────────────────────────────────────────────────────

class MediaQueue {
    constructor() {
        this.queue = [];
        this.isProcessing = false;
        this.senderBatches = new Map();
    }

    enqueue(message, processCallback) {
        const senderKey = message.from;

        if (!this.senderBatches.has(senderKey)) {
            this.senderBatches.set(senderKey, {
                messages: [],
                timer: null
            });
        }

        const batch = this.senderBatches.get(senderKey);
        batch.messages.push({ message, processCallback });

        if (batch.timer) {
            clearTimeout(batch.timer);
        }

        batch.timer = setTimeout(() => {
            this.flushBatch(senderKey);
        }, 300);
    }

    async flushBatch(senderKey) {
        const batch = this.senderBatches.get(senderKey);
        if (!batch || batch.messages.length === 0) return;

        const items = [...batch.messages];
        this.senderBatches.delete(senderKey);

        for (let i = 0; i < items.length; i++) {
            this.queue.push({
                ...items[i],
                batchIndex: i + 1,
                batchTotal: count,
            });
        }

        this.processNext();
    }

    async processNext() {
        if (this.isProcessing) return;
        if (this.queue.length === 0) return;

        this.isProcessing = true;
        const job = this.queue.shift();

        try {
            await job.processCallback(job.message, job.batchIndex, job.batchTotal);
        } catch (err) {
            console.error(`[Queue] Error processing document from ${job.message.from}:`, err.message);
        } finally {
            this.isProcessing = false;
            setTimeout(() => this.processNext(), 100);
        }
    }
}

const mediaQueue = new MediaQueue();

/**
 * Clean & professional document upload response formatter.
 */
async function processDocumentJob(message, batchIndex, batchTotal) {
    try {
        const res = await sendMediaToServer(message);

        if (res && res.success && res.document) {
            const doc = res.document;
            const sizeMB = (doc.file_size / (1024 * 1024)).toFixed(2);
            const isDuplicate = res.message && res.message.includes('sudah pernah disimpan');
            const header = isDuplicate ? '*Dokumen Sudah Pernah Disimpan*' : '*Berhasil Menyimpan Dokumen*';
            const cleanUploader = formatUploaderName(doc.uploader);

            let replyText = `${header}\n\n` +
                `*Judul*: ${doc.title}\n` +
                `*Pengunggah*: ${cleanUploader}\n` +
                `*Ukuran File*: ${sizeMB} MB\n\n` +
                `*Link Google Drive*:\n${doc.gdrive_link}`;

            await sendReply(message, replyText);
            console.log(`[${CLIENT_ID}] ${isDuplicate ? 'Duplikat' : 'Sukses upload'} "${doc.title}" dari ${cleanUploader}`);
        } else {
            await sendReply(message, `Gagal menyimpan dokumen. Silakan coba lagi.`);
        }
    } catch (error) {
        let errMsg = error.response?.data?.detail || error.message || String(error);
        if (error.errors && Array.isArray(error.errors)) {
            errMsg = error.errors.map(e => e.message || String(e)).join('; ');
        }
        const printableMsg = (errMsg === 'r' || !errMsg) ? 'Koneksi ke server DocuSync gagal' : errMsg;
        console.error(`[${CLIENT_ID}] Error processing document:`, printableMsg);
        try {
            await sendReply(message, `Gagal mengunggah dokumen: ${printableMsg}`);
        } catch (_) {}
    }
}

// ─────────────────────────────────────────────────────────────
// Event Handlers
// ─────────────────────────────────────────────────────────────

client.on('qr', (qr) => {
    console.log(`[${CLIENT_ID}] Scan QR code berikut untuk login WhatsApp Bot:`);
    qrcode.generate(qr, { small: true });
});

client.on('ready', async () => {
    botReadyTimestamp = Date.now();
    console.log(`[${CLIENT_ID}] BOT WHATSAPP DOCUSYNC SIAP BEROPERASI!`);
    await checkDocuSyncServer();
    console.log(`[${CLIENT_ID}] Bot hanya memproses pesan baru mulai dari sekarang.`);
    if (ALLOW_ALL_GROUPS) {
        console.log(`[${CLIENT_ID}] Mode: SEMUA GRUP diproses (ALLOW_ALL_GROUPS=true)`);
    } else if (ALLOWED_GROUP_IDS.length > 0) {
        console.log(`[${CLIENT_ID}] Mode: Hanya ${ALLOWED_GROUP_IDS.length} grup yang diizinkan.`);
    } else {
        console.log(`[${CLIENT_ID}] ALLOW_ALL_GROUPS=false dan COMMA_SEPARATED_GROUP_IDS kosong.`);
    }
});

client.on('authenticated', () => {
    console.log(`[${CLIENT_ID}] Autentikasi WhatsApp berhasil.`);
});

client.on('auth_failure', (msg) => {
    console.error(`[${CLIENT_ID}] Autentikasi gagal: ${msg}`);
});

client.on('disconnected', (reason) => {
    console.warn(`[${CLIENT_ID}] Terputus dari WhatsApp: ${reason}`);
});

// In-memory store for pending delete selections per chat ID
const pendingDeletes = new Map();

function getPendingDelete(chatId) {
    const item = pendingDeletes.get(chatId);
    if (!item) return null;
    if (Date.now() - item.timestamp > 5 * 60 * 1000) { // 5 mins expiration
        pendingDeletes.delete(chatId);
        return null;
    }
    return item.docs;
}

// ─────────────────────────────────────────────────────────────
// Message Handler — Processes incoming group & private messages
// ─────────────────────────────────────────────────────────────

client.on('message_create', async (message) => {
    try {
        const body = (message.body || '').trim();
        const lowerBody = body.toLowerCase();
        const isGroup = message.from.endsWith('@g.us');

        // Ignore self-sent messages unless it's a command
        if (message.fromMe && !lowerBody.startsWith('!')) {
            return;
        }

        console.log(`[${CLIENT_ID}] Pesan diterima dari ${message.from}: "${body.substring(0, 40)}" (hasMedia: ${message.hasMedia})`);

        // Group filtering check
        if (isGroup && !ALLOW_ALL_GROUPS) {
            const isCommand = lowerBody.startsWith('!');
            if (!isCommand && ALLOWED_GROUP_IDS.length > 0 && !ALLOWED_GROUP_IDS.includes(message.from)) {
                return;
            }
            if (!isCommand && ALLOWED_GROUP_IDS.length === 0) {
                return;
            }
        }

        // Command: !groupid
        if (lowerBody === '!groupid' || lowerBody === '!id') {
            if (isGroup) {
                await sendReply(message,
                    `*Info Grup WhatsApp*\n\n` +
                    `• Group ID: \`${message.from}\``
                );
            } else {
                await sendReply(message, `Command ini hanya dapat digunakan di dalam grup.`);
            }
            return;
        }

        // Command: !status
        if (lowerBody === '!status') {
            const health = await checkDocuSyncServer();
            const isOnline = !!health;
            let statusText = `*Status DocuSync Bot*\n\n` +
                `• Backend Server: ${isOnline ? 'Online' : 'Offline'}\n` +
                `• Google Drive API: ${health?.gdrive_configured ? 'Terhubung' : 'Belum Aktif'}\n` +
                `• Elasticsearch: ${health?.elasticsearch_online ? 'Terhubung' : 'Offline (SQLite Fallback)'}\n\n` +
                `Kirim file (PDF/DOCX/XLSX) untuk menyimpan ke Google Drive.`;
            
            await sendReply(message, statusText);
            return;
        }

        // Command: !help
        if (lowerBody === '!help' || lowerBody === '!bantuan') {
            let helpText = `*Panduan DocuSync Bot*\n\n` +
                `1. Simpan Dokumen:\n` +
                `   Kirim file (PDF, DOCX, XLSX) atau bagikan link Google Docs/Sheets di grup.\n\n` +
                `2. Cari Dokumen:\n` +
                `   !cari <kata kunci>\n\n` +
                `3. Lihat Dokumen Terbaru:\n` +
                `   !list\n\n` +
                `4. Hapus Dokumen (Admin):\n` +
                `   !hapus <nama_dokumen_atau_id>\n\n` +
                `5. Sinkronisasi GDrive (Admin):\n` +
                `   !sync (bersihkan dokumen yg terhapus di GDrive)\n\n` +
                `6. Cek Status Server:\n` +
                `   !status\n\n` +
                `7. Lihat Group ID:\n` +
                `   !groupid (hanya di grup)`;
            
            await sendReply(message, helpText);
            return;
        }

        // Command: !sync / !sinkron (Admin Only)
        if (lowerBody === '!sync' || lowerBody === '!sinkron') {
            const isAdmin = await isSenderAdmin(message);
            if (!isAdmin) {
                await sendReply(message, `hanya admin yang dapat melakukan sinkronisasi`);
                return;
            }

            try {
                await sendReply(message, `*Memulai Sinkronisasi...*\nMemeriksa status dokumen di Google Drive.`);
                const res = await axios.post(`${DOCUSYNC_BASE_URL}/api/v1/sync`, {}, { timeout: 60000 });

                if (res.data && res.data.success) {
                    const data = res.data;
                    let replyText = `*Sinkronisasi Google Drive Selesai*\n\n` +
                        `• Total Diperiksa: ${data.total_checked} file\n` +
                        `• Dokumen Terhapus di GDrive: ${data.total_cleaned} file\n`;

                    if (data.cleaned_titles && data.cleaned_titles.length > 0) {
                        replyText += `\n*Dokumen yang dibersihkan dari database*:\n`;
                        data.cleaned_titles.forEach((t, idx) => {
                            replyText += `${idx + 1}. ${t}\n`;
                        });
                    }

                    await sendReply(message, replyText);
                    console.log(`[${CLIENT_ID}] Admin sync completed: ${data.total_cleaned}/${data.total_checked} cleaned.`);
                } else {
                    await sendReply(message, `Gagal melakukan sinkronisasi.`);
                }
            } catch (err) {
                console.error(`[${CLIENT_ID}] Error syncing with GDrive:`, err.response?.data?.detail || err.message);
                await sendReply(message, `Gagal sinkronisasi: ${err.response?.data?.detail || err.message}`);
            }
            return;
        }

        // ── Pending Delete Index Selector (e.g. user replies 1, 2, 3 or !hapus 1) ──
        const pendingDocs = getPendingDelete(message.from);
        const trimmedBody = body.trim();
        const numMatch = trimmedBody.match(/^!?hapus\s*(\d+)$/i) || trimmedBody.match(/^(\d+)$/);

        if (pendingDocs && numMatch) {
            const selectedIdx = parseInt(numMatch[1], 10);
            if (selectedIdx >= 1 && selectedIdx <= pendingDocs.length) {
                const isAdmin = await isSenderAdmin(message);
                if (!isAdmin) {
                    await sendReply(message, `hanya admin yang dapat menghapus dokumen`);
                    return;
                }

                const targetDoc = pendingDocs[selectedIdx - 1];
                pendingDeletes.delete(message.from);

                try {
                    const deleteUrl = `${DOCUSYNC_BASE_URL}/api/v1/documents/${targetDoc.id}`;
                    const delRes = await axios.delete(deleteUrl, { timeout: 30000 });

                    if (delRes.data && delRes.data.success) {
                        let replyText = `*Berhasil Menghapus Dokumen*\n\n` +
                            `*Judul*: ${targetDoc.title}\n` +
                            `*Pengunggah*: ${formatUploaderName(targetDoc.uploader)}\n\n` +
                            `Dokumen telah dihapus dari database dan Google Drive.`;
                        await sendReply(message, replyText);
                        console.log(`[${CLIENT_ID}] Admin menghapus dokumen [pilihan ${selectedIdx}] "${targetDoc.title}" (${targetDoc.id})`);
                    } else {
                        await sendReply(message, `Gagal menghapus dokumen.`);
                    }
                } catch (err) {
                    console.error(`[${CLIENT_ID}] Error deleting document by index:`, err.response?.data?.detail || err.message);
                    await sendReply(message, `Gagal menghapus dokumen: ${err.response?.data?.detail || err.message}`);
                }
                return;
            }
        }

        // Command: !hapus <query_atau_id> / !delete <query_atau_id> (Admin Only)
        if (lowerBody.startsWith('!hapus ') || lowerBody.startsWith('!delete ')) {
            const isAdmin = await isSenderAdmin(message);
            if (!isAdmin) {
                await sendReply(message, `hanya admin yang dapat menghapus dokumen`);
                return;
            }

            const targetQuery = body.split(/\s+/).slice(1).join(' ').trim();
            if (!targetQuery) {
                await sendReply(message, `*Cara Menghapus Dokumen*:\nKetik: \`!hapus <Nama_Dokumen>\`\n\n_Contoh_: \`!hapus Revisi Quotation\``);
                return;
            }

            try {
                // 1. Try direct lookup by exact ID first
                let targetDoc = null;
                try {
                    const directRes = await axios.get(`${DOCUSYNC_BASE_URL}/api/v1/documents/${targetQuery}`);
                    if (directRes.data && directRes.data.id) {
                        targetDoc = directRes.data;
                    }
                } catch (_) {}

                let docs = [];
                if (!targetDoc) {
                    // 2. Search for documents by keyword/query
                    const searchRes = await axios.get(DOCUSYNC_SEARCH_URL, {
                        params: { q: targetQuery, page: 1, size: 10 }
                    });
                    docs = searchRes.data?.results || [];

                    if (docs.length === 0) {
                        await sendReply(message, `Tidak ditemukan dokumen dengan kata kunci: *"${targetQuery}"*.`);
                        return;
                    }

                    if (docs.length === 1) {
                        targetDoc = docs[0];
                    }
                }

                // If multiple documents match, ask user to select index (1, 2, 3...)
                if (!targetDoc && docs.length > 1) {
                    pendingDeletes.set(message.from, {
                        timestamp: Date.now(),
                        docs: docs
                    });

                    let multiMsg = `*Ditemukan ${docs.length} Dokumen*:\n\n`;
                    docs.forEach((d, idx) => {
                        multiMsg += `${idx + 1}. *${d.title}*\n   Pengunggah: ${formatUploaderName(d.uploader)}\n\n`;
                    });
                    multiMsg += `Balas dengan angka *1* s/d *${docs.length}* untuk memilih dokumen yang ingin dihapus.`;
                    await sendReply(message, multiMsg);
                    return;
                }

                // 3. Delete single target document
                const deleteUrl = `${DOCUSYNC_BASE_URL}/api/v1/documents/${targetDoc.id}`;
                const delRes = await axios.delete(deleteUrl, { timeout: 30000 });

                if (delRes.data && delRes.data.success) {
                    let replyText = `*Berhasil Menghapus Dokumen*\n\n` +
                        `*Judul*: ${targetDoc.title}\n` +
                        `*Pengunggah*: ${formatUploaderName(targetDoc.uploader)}\n\n` +
                        `Dokumen telah dihapus dari database dan Google Drive.`;
                    await sendReply(message, replyText);
                    console.log(`[${CLIENT_ID}] Admin menghapus dokumen "${targetDoc.title}" (${targetDoc.id})`);
                } else {
                    await sendReply(message, `Gagal menghapus dokumen.`);
                }
            } catch (err) {
                console.error(`[${CLIENT_ID}] Error deleting document:`, err.response?.data?.detail || err.message);
                await sendReply(message, `Gagal menghapus dokumen: ${err.response?.data?.detail || err.message}`);
            }
            return;
        }

        // Command: !cari <keyword>
        if (lowerBody.startsWith('!cari ')) {
            const query = body.substring(6).trim();
            if (!query) {
                await sendReply(message, 'Contoh: `!cari laporan keuangan`');
                return;
            }

            console.log(`[${CLIENT_ID}] Memproses command !cari "${query}" dari ${message.from}...`);
            try {
                const res = await axios.get(DOCUSYNC_SEARCH_URL, {
                    params: { q: query, page: 1, size: 5 },
                    timeout: 5000
                });

                const data = res.data || {};
                const results = data.results || [];
                const total = data.total || 0;

                if (total === 0 || results.length === 0) {
                    await sendReply(message, `Tidak ditemukan dokumen untuk *"${query}"*.`);
                    return;
                }

                let replyText = `*Hasil Pencarian* ("${query}")\nDitemukan: ${total} dokumen\n\n`;
                results.forEach((doc, idx) => {
                    const uploaderName = formatUploaderName(doc.uploader);
                    replyText += `${idx + 1}. *${doc.title}*\n   Pengunggah: ${uploaderName}\n   Link: ${doc.gdrive_link}\n\n`;
                });
                await sendReply(message, replyText);
                console.log(`[${CLIENT_ID}] Sukses mengirim balasan !cari ke ${message.from}`);
            } catch (err) {
                console.error(`[${CLIENT_ID}] Error !cari:`, err.message);
                await sendReply(message, `Gagal pencarian: ${err.response?.data?.detail || err.message}`);
            }
            return;
        }

        // Command: !list
        if (lowerBody === '!list' || lowerBody === '!daftar') {
            console.log(`[${CLIENT_ID}] Memproses command !list dari ${message.from}...`);
            try {
                const res = await axios.get(DOCUSYNC_LIST_URL, {
                    params: { page: 1, size: 5 },
                    timeout: 5000
                });

                const data = res.data || {};
                const docs = data.documents || [];
                const total = data.total || 0;

                if (total === 0 || docs.length === 0) {
                    await sendReply(message, `Belum ada dokumen tersimpan.`);
                    return;
                }

                let replyText = `*Daftar Dokumen Terbaru* (${docs.length}/${total})\n\n`;
                docs.forEach((doc, idx) => {
                    const uploaderName = formatUploaderName(doc.uploader);
                    replyText += `${idx + 1}. *${doc.title}*\n   Pengunggah: ${uploaderName}\n   Link: ${doc.gdrive_link}\n\n`;
                });
                replyText += `_Gunakan !cari <keyword> untuk mencari spesifik._`;
                await sendReply(message, replyText);
                console.log(`[${CLIENT_ID}] Sukses mengirim balasan !list ke ${message.from}`);
            } catch (err) {
                console.error(`[${CLIENT_ID}] Error !list:`, err.message);
                await sendReply(message, `Gagal mengambil daftar: ${err.message}`);
            }
            return;
        }

        // ── Shared Link Listener (Google Docs/Sheets/Drive Links) ────────
        const gdriveUrlRegex = /https?:\/\/(docs|drive)\.google\.com\/[^\s]+/gi;
        const urlMatches = body.match(gdriveUrlRegex);

        if (urlMatches && urlMatches.length > 0) {
            const raw = message._data || {};
            const senderName = raw.notifyName || raw.pushname || message.author?.split('@')[0] || message.from.split('@')[0] || 'User';
            const cleanSenderName = formatUploaderName(senderName);
            const chatSource = isGroup ? `Group: ${message.from}` : `Private: ${cleanSenderName}`;
            const sharedUrl = urlMatches[0];

            try {
                console.log(`[${CLIENT_ID}] Shared Google Drive link terdeteksi: "${sharedUrl}" dari ${cleanSenderName}`);
                const res = await axios.post(DOCUSYNC_SAVE_LINK_URL, {
                    url: sharedUrl,
                    uploader: cleanSenderName,
                    chat_source: chatSource
                }, { timeout: 30000 });

                if (res.data && res.data.success && res.data.document) {
                    const doc = res.data.document;
                    const isDuplicate = res.data.message && res.data.message.includes('sudah pernah disimpan');
                    const header = isDuplicate ? '*Link Dokumen Sudah Pernah Disimpan*' : '*Berhasil Menyimpan Link Dokumen*';
                    const cleanUploader = formatUploaderName(doc.uploader);

                    let replyText = `${header}\n\n` +
                        `*Judul*: ${doc.title}\n` +
                        `*Pengunggah*: ${cleanUploader}\n\n` +
                        `*Link*:\n${doc.gdrive_link}`;
                    await message.reply(replyText);
                    console.log(`[${CLIENT_ID}] ${isDuplicate ? 'Duplikat link' : 'Sukses simpan link'} "${doc.title}" (${cleanUploader})`);
                }
            } catch (err) {
                console.error(`[${CLIENT_ID}] Error saving shared link:`, err.response?.data?.detail || err.message);
                await message.reply(`Gagal menyimpan link dokumen: ${err.response?.data?.detail || err.message}`);
            }
            return;
        }

        // ── File/Document Listener ──────────────────────────────
        if (!message.hasMedia) return;

        const allowedExts = (process.env.ALLOWED_FILE_EXTENSIONS || 'pdf,xls,xlsx,doc,docx')
            .split(',').map(e => e.trim().toLowerCase()).filter(Boolean);

        const rawFilename = message._data?.filename || message.body || message._data?.caption || 'document';
        const ext = (path.extname(rawFilename) || '').toLowerCase().replace('.', '');
        const mimetype = (message._data?.mimetype || message._data?.type || '').toLowerCase();
        const rawSizeBytes = message._data?.size || 0;

        console.log(`[${CLIENT_ID}] Dokumen terdeteksi dari ${message.from}: "${rawFilename}" (mimetype: ${mimetype}, ext: ${ext})`);

        // Check file size against MAX_UPLOAD_SIZE_MB
        if (rawSizeBytes > 0 && rawSizeBytes > MAX_UPLOAD_SIZE_BYTES) {
            console.log(`[${CLIENT_ID}] File "${rawFilename}" diabaikan karena ukuran (${(rawSizeBytes / 1024 / 1024).toFixed(1)} MB) > ${MAX_UPLOAD_SIZE_MB} MB`);
            if (!isGroup) {
                await sendReply(message, `Ukuran file melebihi batas maksimal (${MAX_UPLOAD_SIZE_MB} MB).`);
            }
            return;
        }

        // Broad extension and MIME type validation
        const isPdf = ext === 'pdf' || mimetype.includes('pdf');
        const isExcel = ext === 'xls' || ext === 'xlsx' || mimetype.includes('excel') || mimetype.includes('spreadsheet') || mimetype.includes('sheet');
        const isWord = ext === 'doc' || ext === 'docx' || mimetype.includes('word') || mimetype.includes('wordprocessing');
        const isAllowed = isPdf || isExcel || isWord || (ext && allowedExts.includes(ext));

        if (!isAllowed) {
            console.log(`[${CLIENT_ID}] File "${rawFilename}" diabaikan karena format (ext: "${ext}", mimetype: "${mimetype}") tidak diizinkan.`);
            if (!isGroup) {
                const allowedStr = allowedExts.join(', ').toUpperCase();
                await sendReply(message, `Tipe file tidak diizinkan. Format yang diterima: *${allowedStr}*`);
            }
            return;
        }

        console.log(`[${CLIENT_ID}] Dokumen valid "${rawFilename}" dari ${message.from} — masuk antrean.`);
        mediaQueue.enqueue(message, processDocumentJob);

    } catch (err) {
        if (err.message && err.message.length > 1) {
            console.error(`[${CLIENT_ID}] Message handler error:`, err.message);
        }
    }
});

// ─────────────────────────────────────────────────────────────
// Initialization
// ─────────────────────────────────────────────────────────────

function init() {
    clearChromiumLocks();
    console.log(`[${CLIENT_ID}] Menginisialisasi WhatsApp Client — Menunggu QR code...`);
    client.initialize().catch((err) => {
        console.warn(`[${CLIENT_ID}] Retrying client initialization after notice:`, err.message);
    });
}

init();
