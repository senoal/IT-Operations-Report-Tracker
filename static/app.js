const form = document.querySelector('#name-form');
const nameInput = document.querySelector('#display-name');
const errorMessage = document.querySelector('#name-error');

if (nameInput) {
  nameInput.value = sessionStorage.getItem('reportTrackerName') || '';
  nameInput.focus();
}

form?.addEventListener('submit', (event) => {
  event.preventDefault();
  const name = nameInput.value.trim().replace(/\s+/g, ' ');

  if (name.length < 2) {
    errorMessage.textContent = 'Masukkan nama minimal 2 karakter.';
    nameInput.setAttribute('aria-invalid', 'true');
    nameInput.focus();
    return;
  }

  errorMessage.textContent = '';
  nameInput.removeAttribute('aria-invalid');
  sessionStorage.setItem('reportTrackerName', name);
  document.body.classList.add('leaving');
  window.setTimeout(() => { window.location.href = '/dashboard'; }, 260);
});

const profileName = document.querySelector('#profile-name');
const savedName = sessionStorage.getItem('reportTrackerName') || 'Pengguna';
if (profileName) profileName.textContent = savedName;
const initials = savedName.split(' ').filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase();
const initialsNode = document.querySelector('#profile-initials');
if (initialsNode) initialsNode.textContent = initials || 'RT';

document.querySelector('#change-name')?.addEventListener('click', () => sessionStorage.removeItem('reportTrackerName'));

// Tracking data is rendered from records that have been saved to the database.
const trackingData = document.querySelector('#tracking-data');
const reports = trackingData ? JSON.parse(trackingData.textContent) : [];
const months = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'];
const body = document.querySelector('#report-table-body');
const tableSearch = document.querySelector('#table-search');
const globalSearch = document.querySelector('#global-search');
const yearFilter = document.querySelector('#year-filter');
const toast = document.querySelector('#toast');
const trackingPagination = document.querySelector('#tracking-pagination');
const trackingPageSize = 5;
let trackingPage = 1;

function renderReports() {
  if (!body) return;
  const query = (tableSearch?.value || globalSearch?.value || '').toLowerCase().trim();
  const selectedYear = yearFilter?.value || '';
  const filtered = reports.filter((report) => !selectedYear || Object.keys(report.months).some((key) => key.startsWith(`${selectedYear}-`))).filter((report) => report.name.toLowerCase().includes(query));
  const totalPages = Math.max(1, Math.ceil(filtered.length / trackingPageSize));
  trackingPage = Math.min(trackingPage, totalPages);
  const start = (trackingPage - 1) * trackingPageSize;
  const pageRows = filtered.slice(start, start + trackingPageSize);
  body.innerHTML = pageRows.map((report, index) => `<tr><td>${start + index + 1}</td><td><strong>${report.name}</strong></td>${months.map((month, i) => { const reportMonth = report.months[`${selectedYear}-${i}`]; const complete = Boolean(reportMonth); return `<td><button class="month-status ${complete ? 'complete view-report' : 'missing'}" ${complete ? `data-report-id="${reportMonth.id}"` : ''} title="${complete ? `Klik untuk melihat ringkasan ${month}` : `Belum tersedia untuk ${month}`}" aria-label="Status ${month}">${complete ? '✓' : '—'}</button></td>`; }).join('')}</tr>`).join('') || '<tr><td class="no-results" colspan="14"><div class="empty-state"><span>▤</span><strong>Belum ada laporan</strong><p>Upload PDF laporan untuk mengekstrak dan menyimpan data secara otomatis.</p><a href="/upload-report">Upload Report</a></div></td></tr>';
  const count = document.querySelector('#table-count');
  if (count) count.textContent = filtered.length ? `Menampilkan ${start + 1} - ${Math.min(start + trackingPageSize, filtered.length)} dari ${filtered.length} data` : 'Belum ada data untuk ditampilkan';
  if (trackingPagination) {
    trackingPagination.innerHTML = filtered.length ? `<button type="button" data-page="${trackingPage - 1}" ${trackingPage === 1 ? 'disabled' : ''}>‹ Sebelumnya</button>${Array.from({ length: totalPages }, (_, index) => `<button type="button" data-page="${index + 1}" class="${index + 1 === trackingPage ? 'current' : ''}">${index + 1}</button>`).join('')}<button type="button" data-page="${trackingPage + 1}" ${trackingPage === totalPages ? 'disabled' : ''}>Selanjutnya ›</button>` : '';
  }
}
function resetTrackingPage() { trackingPage = 1; renderReports(); }
if (yearFilter) { const years = [...new Set(reports.flatMap((report) => Object.keys(report.months).map((key) => key.split('-')[0])))].sort().reverse(); yearFilter.innerHTML = years.map((year) => `<option value="${year}">${year}</option>`).join('') || '<option value="">Tahun</option>'; yearFilter.addEventListener('change', resetTrackingPage); }
[tableSearch, globalSearch].forEach((input) => input?.addEventListener('input', resetTrackingPage));
document.querySelector('#search-button')?.addEventListener('click', resetTrackingPage);
trackingPagination?.addEventListener('click', (event) => { const button = event.target.closest('button[data-page]'); if (!button || button.disabled) return; trackingPage = Number(button.dataset.page); renderReports(); });
document.addEventListener('keydown', (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); globalSearch?.focus(); } });
function showToast(message) { if (!toast) return; toast.textContent = message; toast.classList.add('show'); window.setTimeout(() => toast.classList.remove('show'), 2800); }
document.querySelector('#notification-button')?.addEventListener('click', () => showToast('Tidak ada notifikasi baru. Semua laporan Januari telah tercatat.'));
document.querySelectorAll('.muted-nav').forEach((button) => button.addEventListener('click', () => showToast('Halaman ini akan tersedia pada tahap pengembangan berikutnya.')));
const today = document.querySelector('#today-label');
if (today) today.textContent = new Intl.DateTimeFormat('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date());
renderReports();

const reportModal = document.querySelector('#report-modal');
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
function openReportModal(reportId) {
  const record = reports.flatMap((report) => Object.values(report.months)).find((item) => String(item.id) === String(reportId));
  if (!record || !reportModal) return;
  const application = reports.find((report) => Object.values(report.months).some((item) => String(item.id) === String(reportId)))?.name || 'Aplikasi';
  document.querySelector('#modal-title').textContent = application;
  document.querySelector('#modal-subtitle').textContent = `${record.report_id} · ${record.period} · ${record.status}`;
  document.querySelector('#modal-kpis').innerHTML = `<article><span>Availability</span><strong>${escapeHtml(Number(record.availability).toFixed(2))}%</strong></article><article><span>Identity Tickets</span><strong>${escapeHtml(record.tickets)}</strong></article><article><span>SLA Compliance</span><strong>${escapeHtml(Number(record.sla).toFixed(2))}%</strong></article><article><span>Total Incidents</span><strong>${escapeHtml(record.incidents)}</strong></article>`;
  document.querySelector('#modal-detail-link').href = `/reports/${record.id}`;
  reportModal.classList.add('open'); reportModal.setAttribute('aria-hidden', 'false');
}
document.addEventListener('click', (event) => { const button = event.target.closest('.view-report'); if (button) openReportModal(button.dataset.reportId); if (event.target.closest('[data-close-modal]')) { reportModal?.classList.remove('open'); reportModal?.setAttribute('aria-hidden', 'true'); } });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') { reportModal?.classList.remove('open'); reportModal?.setAttribute('aria-hidden', 'true'); } });

const dropZone = document.querySelector('#drop-zone');
const uploadInput = document.querySelector('#report_file');
const dropTitle = document.querySelector('#drop-title');
const dropDescription = document.querySelector('#drop-description');

function setUploadFile(file) {
  if (!file) return;
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
    dropTitle.textContent = 'File harus berformat PDF';
    dropDescription.textContent = 'Silakan pilih atau tarik file laporan dengan ekstensi .pdf.';
    dropZone.classList.add('upload-error');
    return;
  }
  const transfer = new DataTransfer();
  transfer.items.add(file);
  uploadInput.files = transfer.files;
  dropTitle.textContent = file.name;
  dropDescription.textContent = `File siap diekstrak (${Math.ceil(file.size / 1024)} KB).`;
  dropZone.classList.remove('upload-error');
  dropZone.classList.add('file-ready');
}

if (dropZone && uploadInput) {
  ['dragenter', 'dragover'].forEach((eventName) => dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.add('drag-active'); }));
  ['dragleave', 'drop'].forEach((eventName) => dropZone.addEventListener(eventName, (event) => { event.preventDefault(); dropZone.classList.remove('drag-active'); }));
  dropZone.addEventListener('drop', (event) => setUploadFile(event.dataTransfer.files[0]));
  uploadInput.addEventListener('change', () => setUploadFile(uploadInput.files[0]));
}
