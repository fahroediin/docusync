const assert = require('assert');
const path = require('path');

// Test 1: formatUploaderName
function formatUploaderName(str) {
    if (!str) return '-';
    let clean = str.replace(/\s*\([\d\w@._-]+\)\s*$/, '').trim();
    clean = clean.replace(/@c\.us|@g\.us/gi, '').trim();
    return clean || str;
}

assert.strictEqual(formatUploaderName('Fahrudin (@c.us)'), 'Fahrudin');
assert.strictEqual(formatUploaderName('User123'), 'User123');
assert.strictEqual(formatUploaderName(''), '-');
console.log('✓ Test 1 passed: formatUploaderName');

// Test 2: Document extension and MIME classifier
function classifyDocument(filename, mimetype) {
    const allowedExts = ['pdf', 'xls', 'xlsx', 'doc', 'docx'];
    const rawFilename = filename || 'document';
    const ext = (path.extname(rawFilename) || '').toLowerCase().replace('.', '');
    const mime = (mimetype || '').toLowerCase();

    const isPdf = ext === 'pdf' || mime.includes('pdf');
    const isExcel = ext === 'xls' || ext === 'xlsx' || mime.includes('excel') || mime.includes('spreadsheet') || mime.includes('sheet');
    const isWord = ext === 'doc' || ext === 'docx' || mime.includes('word') || mime.includes('wordprocessing');
    const isAllowed = isPdf || isExcel || isWord || (ext && allowedExts.includes(ext));

    return { ext, mime, isAllowed };
}

assert.strictEqual(classifyDocument('Laporan.pdf', 'application/pdf').isAllowed, true);
assert.strictEqual(classifyDocument('Data.xlsx', 'application/vnd.ms-excel').isAllowed, true);
assert.strictEqual(classifyDocument('Notes.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document').isAllowed, true);
assert.strictEqual(classifyDocument('photo.jpg', 'image/jpeg').isAllowed, false);
console.log('✓ Test 2 passed: classifyDocument');

// Test 3: !list API response formatter
function formatListResponse(data) {
    const docs = data.documents || [];
    const total = data.total || 0;
    if (total === 0 || docs.length === 0) {
        return 'Belum ada dokumen tersimpan.';
    }
    let replyText = `*Daftar Dokumen Terbaru* (${docs.length}/${total})\n\n`;
    docs.forEach((doc, idx) => {
        const uploaderName = formatUploaderName(doc.uploader);
        replyText += `${idx + 1}. *${doc.title}*\n   Pengunggah: ${uploaderName}\n   Link: ${doc.gdrive_link}\n\n`;
    });
    replyText += `_Gunakan !cari <keyword> untuk mencari spesifik._`;
    return replyText;
}

const mockListOutput = formatListResponse({
    total: 1,
    documents: [{ title: 'Doc 1', uploader: 'John', gdrive_link: 'http://drive.com/1' }]
});
assert.ok(mockListOutput.includes('Doc 1'));
assert.ok(mockListOutput.includes('John'));
console.log('✓ Test 3 passed: formatListResponse');

console.log('\nALL 3 UNIT TESTS PASSED CLEANLY!');
