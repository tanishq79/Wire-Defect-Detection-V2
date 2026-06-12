// ══════════════════════════════════════════════════════════════
//  SurfaceAI – Wire Inspection – script.js
// ══════════════════════════════════════════════════════════════

// ── Config ──────────────────────────────────────────────────
const DEFAULT_API_BASE = window.location.port === "3000"
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : window.location.origin;
let API_BASE = DEFAULT_API_BASE || "http://127.0.0.1:8000";
let MIN_CONF = 50;       // threshold from settings slider

// ── Session state ────────────────────────────────────────────
let total = 0, defects = 0, ok = 0;
let counts = { defected_wire: 0, ok_wire: 0 };
let historyLog = [];        // { prediction, confidence, time, fileName, color, verdict }
let selectedFile = null;
let loaderInterval = null;
let sessionStart = Date.now();
let systemInfo = {};        // filled by /status poll
let lastResult = null;      // last prediction result for single PDF export
let activeSourceName = "";
let cameraPreviewActive = false;

// ── Colour / meta map ────────────────────────────────────────
const META = {
    ok_wire:       { color: "#059669", bg: "#ecfdf5", border: "#a7f3d0", label: "OK WIRE",       verdict: "PASS",   action: "ACCEPT — No defects detected on wire" },
    defected_wire: { color: "#dc2626", bg: "#fef2f2", border: "#fecaca", label: "DEFECTED WIRE", verdict: "REJECT", action: "REJECT — Wire defect detected" },
};

document.getElementById("cfg-apiUrl").value = API_BASE;

async function readApiError(res) {
    try {
        const data = await res.json();
        return data.detail || data.message || JSON.stringify(data);
    } catch {
        return await res.text();
    }
}

if (!window.Chart) {
    window.Chart = class {
        constructor(_ctx, config) {
            this.data = config && config.data ? config.data : { datasets: [{ data: [] }] };
        }
        update() {}
        destroy() {}
    };
}

// ══════════════════════════════════════════════════════════════
//  NAVIGATION
// ══════════════════════════════════════════════════════════════
const PAGE_TITLES = {
    inspection: ["Wire Inspection", "LIVE SESSION"],
    analytics:  ["Analytics",       "SESSION DATA"],
    reports:    ["Reports",         "EXPORT READY"],
    settings:   ["Settings",        "CONFIGURATION"],
};

document.querySelectorAll(".nav-item").forEach(link => {
    link.addEventListener("click", e => {
        e.preventDefault();
        const page = link.dataset.page;
        switchPage(page);
    });
});

function switchPage(page) {
    document.querySelectorAll(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.page === page));
    document.querySelectorAll(".page").forEach(p => p.classList.toggle("hidden", p.id !== `page-${page}`));
    const [title, tag] = PAGE_TITLES[page] || ["", ""];
    document.getElementById("pageTitle").textContent = title;
    document.getElementById("pageTag").textContent   = tag;

    if (page === "analytics") refreshAnalytics();
    if (page === "reports")   refreshReports();
}

// ══════════════════════════════════════════════════════════════
//  CLOCK
// ══════════════════════════════════════════════════════════════
function tick() {
    document.getElementById("clock").textContent =
        new Date().toLocaleTimeString("en-GB", { hour12: false });
}
tick();
setInterval(tick, 1000);

// ══════════════════════════════════════════════════════════════
//  LIVE STATUS POLL  (hits /status every 4 s)
// ══════════════════════════════════════════════════════════════
async function pollStatus() {
    try {
        const res  = await fetch(`${API_BASE}/status`, { signal: AbortSignal.timeout(3000) });
        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        systemInfo = data;

        setDot("dot-model", "green");
        document.getElementById("status-model").textContent = data.model_name + " Active";

        setDot("dot-api", "green");
        document.getElementById("status-api").textContent = "API Connected";

        if (data.gpu_available) {
            const util = data.gpu_utilization != null ? `GPU ${data.gpu_utilization}%` : "GPU Active";
            const dot  = data.gpu_utilization != null && data.gpu_utilization > 80 ? "amber" : "green";
            setDot("dot-gpu", dot);
            document.getElementById("status-gpu").textContent = util;
        } else {
            setDot("dot-gpu", "amber");
            document.getElementById("status-gpu").textContent = "CPU Mode";
        }

        checkCameraStatus();

    } catch {
        setDot("dot-model", "red");  document.getElementById("status-model").textContent = "Model Offline";
        setDot("dot-api",   "red");  document.getElementById("status-api").textContent   = "API Unreachable";
        setDot("dot-gpu",   "red");  document.getElementById("status-gpu").textContent   = "—";
    }
}

function setDot(id, cls) {
    const el = document.getElementById(id);
    el.className = "dot " + cls;
}

pollStatus();
setInterval(pollStatus, 4000);

// ══════════════════════════════════════════════════════════════
//  FILE HANDLING
// ══════════════════════════════════════════════════════════════
document.getElementById("fileElem").addEventListener("change", e => {
    if (e.target.files[0]) loadFile(e.target.files[0]);
});

function handleDrop(e) {
    e.preventDefault();
    document.getElementById("drop-area").classList.remove("drag-over");
    const f = e.dataTransfer.files[0];
    if (f && f.type.startsWith("image/")) loadFile(f);
}

function loadFile(file) {
    selectedFile = file;
    activeSourceName = file.name;
    document.getElementById("previewImage").src = URL.createObjectURL(file);
    document.getElementById("drop-area").style.display   = "none";
    document.getElementById("previewWrap").style.display = "block";
    document.getElementById("resultPanel").style.display = "none";
    lastResult = null;
}

function resetPreviewForRemoteSource(label) {
    selectedFile = null;
    activeSourceName = label;
    document.getElementById("drop-area").style.display = "block";
    document.getElementById("previewWrap").style.display = "none";
    document.getElementById("resultPanel").style.display = "none";
    lastResult = null;
}

// ══════════════════════════════════════════════════════════════
//  LOADER
// ══════════════════════════════════════════════════════════════
function startLoader() {
    const bar  = document.getElementById("loaderBar");
    const fill = document.getElementById("loaderFill");
    bar.style.display = "block";
    fill.style.width  = "0%";
    let w = 0;
    loaderInterval = setInterval(() => {
        w = Math.min(w + Math.random() * 8, 85);
        fill.style.width = w + "%";
    }, 150);
}

function stopLoader() {
    clearInterval(loaderInterval);
    const fill = document.getElementById("loaderFill");
    fill.style.width = "100%";
    setTimeout(() => {
        document.getElementById("loaderBar").style.display = "none";
        fill.style.width = "0%";
    }, 400);
}

// ══════════════════════════════════════════════════════════════
//  PREDICT
// ══════════════════════════════════════════════════════════════
async function predict() {
    if (!selectedFile) { alert("Please upload a wire image first."); return; }

    const btn = document.getElementById("runBtn");
    btn.disabled = true; btn.style.opacity = "0.7";
    startLoader();

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
        const res  = await fetch(`${API_BASE}/predict`, { method: "POST", body: formData });
        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        applyPredictionResult(data, selectedFile.name);
    } catch (err) {
        stopLoader();
        btn.disabled = false; btn.style.opacity = "1";
        alert(`Inspection failed: ${err.message || "Could not reach the model API."}`);
        return;
    }

    stopLoader();
    btn.disabled = false; btn.style.opacity = "1";
}

async function predictStoredPath() {
    const path = document.getElementById("storedPath").value.trim();
    if (!path) { alert("Enter an image path stored on the Raspberry Pi first."); return; }

    resetPreviewForRemoteSource(path);
    startLoader();

    try {
        const url = `${API_BASE}/predict-path?path=${encodeURIComponent(path)}`;
        const res = await fetch(url, { method: "POST" });
        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        applyPredictionResult(data, path);
    } catch (err) {
        alert(`Stored image inspection failed: ${err.message || "API error"}`);
    } finally {
        stopLoader();
    }
}

async function captureCamera() {
    resetPreviewForRemoteSource("camera_capture");
    startLoader();

    try {
        const res = await fetch(`${API_BASE}/capture`, { method: "POST" });
        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        if (data.path) {
            activeSourceName = data.path;
            document.getElementById("storedPath").value = data.path;
        }
        applyPredictionResult(data, data.path || "camera_capture");
    } catch (err) {
        alert(`Camera capture failed: ${err.message || "API error"}`);
    } finally {
        stopLoader();
    }
}

async function checkCameraStatus() {
    const badge = document.getElementById("cameraStatus");
    if (!badge) return;

    try {
        const res = await fetch(`${API_BASE}/camera/status`, { signal: AbortSignal.timeout(3000) });
        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        badge.textContent = data.available ? data.model || "Ready" : "Unavailable";
        badge.classList.toggle("camera-ready", !!data.available);
    } catch {
        badge.textContent = "Unavailable";
        badge.classList.remove("camera-ready");
    }
}

function startCameraPreview() {
    const preview = document.getElementById("cameraPreview");
    const empty = document.getElementById("cameraEmpty");
    const badge = document.getElementById("cameraStatus");

    cameraPreviewActive = true;
    preview.src = `${API_BASE}/camera/stream?ts=${Date.now()}`;
    preview.style.display = "block";
    empty.style.display = "none";
    badge.textContent = "Live";
    badge.classList.add("camera-ready");
}

async function stopCameraPreview() {
    const preview = document.getElementById("cameraPreview");
    const empty = document.getElementById("cameraEmpty");
    const badge = document.getElementById("cameraStatus");

    cameraPreviewActive = false;
    preview.removeAttribute("src");
    preview.style.display = "none";
    empty.style.display = "flex";

    try {
        await fetch(`${API_BASE}/camera/stop`, { method: "POST" });
    } catch {}

    badge.textContent = "Stopped";
    badge.classList.remove("camera-ready");
}

function applyPredictionResult(data, sourceName) {
    const prediction = data.prediction;
    const confidence = parseFloat(parseFloat(data.confidence).toFixed(1));

    const m          = META[prediction] || META.ok_wire;
    const timeStr    = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const dateStr    = new Date().toLocaleDateString("en-CA");   // YYYY-MM-DD
    const isLowConf  = confidence < MIN_CONF;
    const fileName   = sourceName || activeSourceName || data.filename || data.path || "camera_capture";

    // ── Result panel ──────────────────────────────────────────
    const panel = document.getElementById("resultPanel");
    panel.style.display = "block";

    const badge = document.getElementById("resultBadge");
    badge.textContent       = m.label;
    badge.style.background  = m.bg;
    badge.style.color       = m.color;
    badge.style.borderColor = m.border;

    const actionEl = document.getElementById("resultAction");
    actionEl.textContent = prediction === "ok_wire" ? "✓ PASS" : "✕ REJECT";
    actionEl.style.color = m.color;

    document.getElementById("predictionText").textContent = m.label;
    document.getElementById("predictionText").style.color = m.color;
    document.getElementById("confidenceText").textContent = confidence + "%";

    const fill = document.getElementById("confidenceFill");
    fill.style.width      = confidence + "%";
    fill.style.background = m.color;

    let noteText = "⟶ " + m.action;
    if (isLowConf) noteText += "\n⚠ Low confidence — consider re-imaging the wire sample.";
    document.getElementById("actionText").textContent = noteText;

    // ── Save last result for single PDF ───────────────────────
    lastResult = { prediction, confidence, timeStr, dateStr, fileName, verdict: m.verdict, label: m.label };

    // ── Session counters ──────────────────────────────────────
    total++;
    counts[prediction]++;
    if (prediction === "ok_wire") ok++; else defects++;

    document.getElementById("totalCount").textContent  = total;
    document.getElementById("defectCount").textContent = defects;
    document.getElementById("okCount").textContent     = ok;
    document.getElementById("defectRate").textContent  = total > 0 ? ((defects / total) * 100).toFixed(0) + "%" : "—";

    // ── History ───────────────────────────────────────────────
    historyLog.unshift({ prediction, classLabel: m.label, confidence, time: timeStr, date: dateStr, fileName, color: m.color, verdict: m.verdict });
    renderHistory();
    updateBarChart();
}

// ══════════════════════════════════════════════════════════════
//  HISTORY LIST (Inspection page)
// ══════════════════════════════════════════════════════════════
function renderHistory() {
    const list = document.getElementById("historyList");
    document.getElementById("logCount").textContent = historyLog.length + " entr" + (historyLog.length === 1 ? "y" : "ies");
    if (!historyLog.length) { list.innerHTML = '<div class="history-empty">No inspections yet</div>'; return; }
    list.innerHTML = historyLog.map(h => `
        <div class="history-item">
            <div class="history-item-left">
                <div class="history-dot" style="background:${h.color}"></div>
                <span class="history-class">${h.classLabel}</span>
            </div>
            <div style="display:flex;align-items:center;gap:8px">
                <span class="history-conf">${h.confidence}%</span>
                <span class="history-time">${h.time}</span>
            </div>
        </div>`).join("");
}

// ══════════════════════════════════════════════════════════════
//  BAR CHART (Inspection page)
// ══════════════════════════════════════════════════════════════
const barChart = new Chart(document.getElementById("chart"), {
    type: "bar",
    data: {
        labels: ["Defected", "OK"],
        datasets: [{
            label: "Inspections",
            data:  [0, 0],
            backgroundColor: ["#dc2626cc", "#059669cc"],
            borderColor:     ["#dc2626",   "#059669"],
            borderWidth: 1.5,
            borderRadius: 5,
            borderSkipped: false,
        }]
    },
    options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: { backgroundColor: "#111827", titleFont: { family: "'DM Mono',monospace", size: 11 }, bodyFont: { family: "'DM Mono',monospace", size: 12 }, padding: 10, cornerRadius: 6 }
        },
        scales: {
            x: { grid: { display: false }, ticks: { font: { family: "'DM Mono',monospace", size: 11 }, color: "#9ca3af" }, border: { color: "#e4e7ed" } },
            y: { beginAtZero: true, ticks: { stepSize: 1, font: { family: "'DM Mono',monospace", size: 11 }, color: "#9ca3af" }, grid: { color: "#f0f2f5" }, border: { color: "#e4e7ed", dash: [4, 4] } }
        }
    }
});

function updateBarChart() {
    barChart.data.datasets[0].data = [counts.defected_wire, counts.ok_wire];
    barChart.update();
}

// ══════════════════════════════════════════════════════════════
//  ANALYTICS PAGE
// ══════════════════════════════════════════════════════════════
let lineChartInst = null;
let doughnutInst  = null;

function refreshAnalytics() {
    // Duration
    const secs = Math.floor((Date.now() - sessionStart) / 1000);
    const mm   = String(Math.floor(secs / 60)).padStart(2, "0");
    const ss   = String(secs % 60).padStart(2, "0");
    document.getElementById("an-duration").textContent = `${mm}:${ss}`;

    // Avg confidence
    const avg = historyLog.length
        ? (historyLog.reduce((a, b) => a + b.confidence, 0) / historyLog.length).toFixed(1) + "%"
        : "—";
    document.getElementById("an-avgConf").textContent = avg;

    // Defected wire count
    document.getElementById("an-worst").textContent = counts.defected_wire > 0 ? counts.defected_wire : "—";

    // Pass rate
    document.getElementById("an-passRate").textContent = total > 0 ? ((ok / total) * 100).toFixed(0) + "%" : "—";

    // Timeline table
    const tbody = document.getElementById("timelineBody");
    if (!historyLog.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty-td">No data yet — run an inspection first.</td></tr>`;
    } else {
        tbody.innerHTML = historyLog.map((h, i) => {
            const m      = META[h.prediction] || META.ok_wire;
            const vClass = h.verdict === "PASS" ? "verdict-pass" : "verdict-flag";
            return `<tr>
                <td style="font-family:var(--font-mono);color:var(--text-muted)">${historyLog.length - i}</td>
                <td><span class="td-class" style="background:${m.bg};color:${m.color};border-color:${m.border}">${h.classLabel}</span></td>
                <td style="font-family:var(--font-mono)">${h.confidence}%</td>
                <td style="font-family:var(--font-mono)">${h.time}</td>
                <td class="${vClass}">${h.verdict}</td>
            </tr>`;
        }).join("");
    }

    // Line chart – confidence over time
    const labels   = historyLog.map((_, i) => `#${historyLog.length - i}`).reverse();
    const confData = [...historyLog].reverse().map(h => h.confidence);

    if (lineChartInst) lineChartInst.destroy();
    lineChartInst = new Chart(document.getElementById("lineChart"), {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Confidence %",
                data: confData,
                borderColor: "#1a56db",
                backgroundColor: "rgba(26,86,219,.08)",
                borderWidth: 2,
                tension: 0.35,
                pointRadius: 4,
                pointBackgroundColor: "#1a56db",
                fill: true,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { backgroundColor: "#111827", bodyFont: { family: "'DM Mono',monospace", size: 12 }, padding: 10, cornerRadius: 6 } },
            scales: {
                x: { grid: { display: false }, ticks: { font: { family: "'DM Mono',monospace", size: 10 }, color: "#9ca3af" } },
                y: { min: 0, max: 100, ticks: { font: { family: "'DM Mono',monospace", size: 10 }, color: "#9ca3af" }, grid: { color: "#f0f2f5" } }
            }
        }
    });

    // Doughnut chart
    if (doughnutInst) doughnutInst.destroy();
    doughnutInst = new Chart(document.getElementById("doughnutChart"), {
        type: "doughnut",
        data: {
            labels: ["Defected", "OK"],
            datasets: [{
                data: [counts.defected_wire, counts.ok_wire],
                backgroundColor: ["#dc2626cc", "#059669cc"],
                borderColor: ["#dc2626", "#059669"],
                borderWidth: 2,
                hoverOffset: 6,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false, cutout: "65%",
            plugins: {
                legend: { position: "right", labels: { font: { family: "'DM Sans',sans-serif", size: 12 }, color: "#6b7280", padding: 14, usePointStyle: true } },
                tooltip: { backgroundColor: "#111827", bodyFont: { family: "'DM Mono',monospace", size: 12 }, padding: 10, cornerRadius: 6 }
            }
        }
    });
}

// ══════════════════════════════════════════════════════════════
//  REPORTS PAGE
// ══════════════════════════════════════════════════════════════
function refreshReports() {
    document.getElementById("rpt-total").textContent    = total;
    document.getElementById("rpt-defects").textContent  = defects;
    document.getElementById("rpt-ok").textContent       = ok;
    document.getElementById("rpt-rate").textContent     = total > 0 ? ((defects / total) * 100).toFixed(1) + "%" : "—";
    document.getElementById("rpt-pass").textContent     = total > 0 ? ((ok / total) * 100).toFixed(1) + "%" : "—";
    const avg = historyLog.length
        ? (historyLog.reduce((a, b) => a + b.confidence, 0) / historyLog.length).toFixed(1) + "%"
        : "—";
    document.getElementById("rpt-conf").textContent     = avg;

    document.getElementById("rpt-defected").textContent = counts.defected_wire;
    document.getElementById("rpt-okc").textContent      = counts.ok_wire;

    document.getElementById("rpt-model").textContent    = systemInfo.model_name   || "MobileNet-V2";
    document.getElementById("rpt-device").textContent   = systemInfo.device        || "—";
    document.getElementById("rpt-gpu").textContent      = systemInfo.gpu_available ? "Yes" : (systemInfo.device ? "No" : "—");
    document.getElementById("rpt-start").textContent    = new Date(sessionStart).toLocaleTimeString("en-GB", { hour12: false });
    document.getElementById("rpt-gen").textContent      = new Date().toLocaleTimeString("en-GB", { hour12: false });

    const tbody = document.getElementById("reportBody");
    if (!historyLog.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-td">No data yet.</td></tr>`;
        return;
    }
    tbody.innerHTML = historyLog.map((h, i) => {
        const m      = META[h.prediction] || META.ok_wire;
        const vClass = h.verdict === "PASS" ? "verdict-pass" : "verdict-flag";
        return `<tr>
            <td style="font-family:var(--font-mono);color:var(--text-muted)">${historyLog.length - i}</td>
            <td><span class="td-class" style="background:${m.bg};color:${m.color};border-color:${m.border}">${h.classLabel}</span></td>
            <td style="font-family:var(--font-mono)">${h.confidence}%</td>
            <td style="font-family:var(--font-mono);color:var(--text-muted);font-size:11px">${h.fileName || "—"}</td>
            <td style="font-family:var(--font-mono)">${h.time}</td>
            <td class="${vClass}">${h.verdict}</td>
        </tr>`;
    }).join("");
}

function exportCSV() {
    if (!historyLog.length) { alert("No data to export yet."); return; }
    const header = ["#", "Class", "Confidence (%)", "File Name", "Time", "Verdict"];
    const rows   = historyLog.map((h, i) => [
        historyLog.length - i, h.classLabel, h.confidence, h.fileName || "", h.time, h.verdict
    ]);
    const csv  = [header, ...rows].map(r => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const a    = document.createElement("a");
    a.href     = URL.createObjectURL(blob);
    a.download = `wireai_session_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
}

// ══════════════════════════════════════════════════════════════
//  PDF EXPORT — single inspection result
// ══════════════════════════════════════════════════════════════
function exportSinglePDF() {
    if (!lastResult) { alert("No inspection result to export yet."); return; }
    if (!window.jspdf) { alert("PDF export library is not loaded. Check internet connection or export CSV instead."); return; }
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ unit: "mm", format: "a4" });

    const pageW = doc.internal.pageSize.getWidth();
    const margin = 20;
    let y = margin;

    // ── Header bar ────────────────────────────────────────────
    doc.setFillColor(26, 86, 219);
    doc.rect(0, 0, pageW, 28, "F");

    doc.setFont("helvetica", "bold");
    doc.setFontSize(16);
    doc.setTextColor(255, 255, 255);
    doc.text("WIRE INSPECTION REPORT", margin, 17);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(200, 220, 255);
    doc.text("SurfaceAI — Automated Wire Defect Detection System", margin, 23);

    y = 40;

    // ── Date / Time row ───────────────────────────────────────
    doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.setTextColor(100, 100, 120);
    doc.text("DATE", margin, y);
    doc.text("TIME", margin + 60, y);
    doc.text("GENERATED BY", margin + 120, y);

    y += 5;
    doc.setFont("helvetica", "normal");
    doc.setFontSize(11);
    doc.setTextColor(17, 24, 39);
    doc.text(lastResult.dateStr, margin, y);
    doc.text(lastResult.timeStr, margin + 60, y);
    doc.text("SurfaceAI v2.1", margin + 120, y);

    y += 12;
    doc.setDrawColor(228, 231, 237);
    doc.setLineWidth(0.3);
    doc.line(margin, y, pageW - margin, y);
    y += 10;

    // ── Main result card ──────────────────────────────────────
    const isDefected = lastResult.prediction === "defected_wire";
    const cardColor  = isDefected ? [254, 242, 242] : [236, 253, 245];
    const accentRGB  = isDefected ? [220, 38, 38]   : [5, 150, 105];

    doc.setFillColor(...cardColor);
    doc.roundedRect(margin, y, pageW - margin * 2, 52, 3, 3, "F");
    doc.setDrawColor(...accentRGB);
    doc.setLineWidth(0.8);
    doc.line(margin, y, margin, y + 52);

    doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.setTextColor(100, 100, 120);
    doc.text("PREDICTED CLASS", margin + 6, y + 10);

    doc.setFont("helvetica", "bold");
    doc.setFontSize(20);
    doc.setTextColor(...accentRGB);
    doc.text(lastResult.label, margin + 6, y + 22);

    doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.setTextColor(100, 100, 120);
    doc.text("CONFIDENCE", margin + 6, y + 32);

    doc.setFont("helvetica", "bold");
    doc.setFontSize(16);
    doc.setTextColor(17, 24, 39);
    doc.text(lastResult.confidence + "%", margin + 6, y + 43);

    // Verdict badge (right side)
    const verdictBg = isDefected ? [220, 38, 38] : [5, 150, 105];
    doc.setFillColor(...verdictBg);
    doc.roundedRect(pageW - margin - 38, y + 14, 32, 14, 2, 2, "F");
    doc.setFont("helvetica", "bold");
    doc.setFontSize(12);
    doc.setTextColor(255, 255, 255);
    const verdictText = lastResult.verdict;
    const vW = doc.getTextWidth(verdictText);
    doc.text(verdictText, pageW - margin - 22 - vW / 2, y + 24);

    y += 62;

    // ── Details table ─────────────────────────────────────────
    doc.setDrawColor(228, 231, 237);
    doc.setLineWidth(0.3);
    doc.line(margin, y, pageW - margin, y);
    y += 8;

    const rows = [
        ["File Name",    lastResult.fileName],
        ["Inspection Date", lastResult.dateStr],
        ["Inspection Time", lastResult.timeStr],
        ["Prediction",   lastResult.label],
        ["Confidence",   lastResult.confidence + "%"],
        ["Verdict",      lastResult.verdict],
        ["Model",        systemInfo.model_name || "MobileNet-V2"],
        ["Device",       systemInfo.device      || "—"],
    ];

    rows.forEach(([key, val]) => {
        doc.setFont("helvetica", "bold");
        doc.setFontSize(9);
        doc.setTextColor(107, 114, 128);
        doc.text(key.toUpperCase(), margin, y);

        doc.setFont("helvetica", "normal");
        doc.setFontSize(10);
        doc.setTextColor(17, 24, 39);
        doc.text(String(val), margin + 55, y);

        y += 8;
        doc.setDrawColor(240, 242, 245);
        doc.setLineWidth(0.2);
        doc.line(margin, y - 2, pageW - margin, y - 2);
    });

    y += 8;

    // ── Action note ───────────────────────────────────────────
    const meta = META[lastResult.prediction] || META.ok_wire;
    doc.setFillColor(248, 249, 251);
    doc.roundedRect(margin, y, pageW - margin * 2, 18, 2, 2, "F");
    doc.setFont("helvetica", "italic");
    doc.setFontSize(10);
    doc.setTextColor(107, 114, 128);
    doc.text("⟶  " + meta.action, margin + 4, y + 11);

    y += 28;

    // ── Footer ────────────────────────────────────────────────
    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.setTextColor(156, 163, 175);
    doc.text(
        `Generated by SurfaceAI Wire Inspection System  |  ${lastResult.dateStr} ${lastResult.timeStr}`,
        margin, doc.internal.pageSize.getHeight() - 10
    );

    doc.save(`wire_inspection_${lastResult.dateStr}_${lastResult.timeStr.replace(/:/g, "-")}.pdf`);
}

// ══════════════════════════════════════════════════════════════
//  PDF EXPORT — full session report
// ══════════════════════════════════════════════════════════════
function exportSessionPDF() {
    if (!historyLog.length) { alert("No data to export yet."); return; }
    if (!window.jspdf) { alert("PDF export library is not loaded. Check internet connection or export CSV instead."); return; }
    const { jsPDF } = window.jspdf;
    const doc    = new jsPDF({ unit: "mm", format: "a4" });
    const pageW  = doc.internal.pageSize.getWidth();
    const margin = 20;
    let y = margin;

    // Header
    doc.setFillColor(26, 86, 219);
    doc.rect(0, 0, pageW, 28, "F");
    doc.setFont("helvetica", "bold");
    doc.setFontSize(16);
    doc.setTextColor(255, 255, 255);
    doc.text("WIRE INSPECTION — SESSION REPORT", margin, 17);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(200, 220, 255);
    doc.text(`Generated: ${new Date().toLocaleString("en-GB", { hour12: false })}`, margin, 23);

    y = 40;

    // Summary stats
    const summaryItems = [
        ["Total Inspected", total],
        ["Defected Wires",  defects],
        ["OK Wires",        ok],
        ["Defect Rate",     total > 0 ? ((defects / total) * 100).toFixed(1) + "%" : "—"],
        ["Pass Rate",       total > 0 ? ((ok / total) * 100).toFixed(1) + "%" : "—"],
        ["Avg Confidence",  historyLog.length ? (historyLog.reduce((a, b) => a + b.confidence, 0) / historyLog.length).toFixed(1) + "%" : "—"],
        ["Model",           systemInfo.model_name || "MobileNet-V2"],
        ["Device",          systemInfo.device || "—"],
    ];

    doc.setFont("helvetica", "bold");
    doc.setFontSize(11);
    doc.setTextColor(17, 24, 39);
    doc.text("SESSION SUMMARY", margin, y);
    y += 6;
    doc.setDrawColor(228, 231, 237);
    doc.setLineWidth(0.3);
    doc.line(margin, y, pageW - margin, y);
    y += 6;

    summaryItems.forEach(([key, val]) => {
        doc.setFont("helvetica", "bold");
        doc.setFontSize(9);
        doc.setTextColor(107, 114, 128);
        doc.text(key.toUpperCase(), margin, y);
        doc.setFont("helvetica", "normal");
        doc.setFontSize(10);
        doc.setTextColor(17, 24, 39);
        doc.text(String(val), margin + 60, y);
        y += 7;
        doc.setDrawColor(240, 242, 245);
        doc.setLineWidth(0.15);
        doc.line(margin, y - 2, pageW - margin, y - 2);
    });

    y += 8;

    // Inspection log header
    doc.setFont("helvetica", "bold");
    doc.setFontSize(11);
    doc.setTextColor(17, 24, 39);
    doc.text("INSPECTION LOG", margin, y);
    y += 6;
    doc.setDrawColor(228, 231, 237);
    doc.setLineWidth(0.3);
    doc.line(margin, y, pageW - margin, y);
    y += 6;

    // Table header
    doc.setFillColor(248, 249, 251);
    doc.rect(margin, y - 2, pageW - margin * 2, 8, "F");
    doc.setFont("helvetica", "bold");
    doc.setFontSize(8);
    doc.setTextColor(107, 114, 128);
    const cols = [margin, margin + 10, margin + 58, margin + 90, margin + 120, margin + 148];
    ["#", "CLASS", "CONFIDENCE", "FILE", "TIME", "VERDICT"].forEach((h, i) => doc.text(h, cols[i], y + 4));
    y += 10;

    // Table rows
    [...historyLog].reverse().forEach((h, i) => {
        if (y > 270) {
            doc.addPage();
            y = margin;
        }
        const isEven = i % 2 === 0;
        if (isEven) {
            doc.setFillColor(252, 252, 253);
            doc.rect(margin, y - 2, pageW - margin * 2, 7, "F");
        }

        const isDefected = h.prediction === "defected_wire";
        doc.setFont("helvetica", "normal");
        doc.setFontSize(8);
        doc.setTextColor(107, 114, 128);
        doc.text(String(i + 1), cols[0], y + 3);

        doc.setTextColor(...(isDefected ? [220, 38, 38] : [5, 150, 105]));
        doc.text(h.classLabel, cols[1], y + 3);

        doc.setTextColor(17, 24, 39);
        doc.text(h.confidence + "%", cols[2], y + 3);

        doc.setTextColor(107, 114, 128);
        const fn = (h.fileName || "—").slice(0, 22);
        doc.text(fn, cols[3], y + 3);
        doc.text(h.time, cols[4], y + 3);

        doc.setTextColor(...(h.verdict === "PASS" ? [5, 150, 105] : [220, 38, 38]));
        doc.setFont("helvetica", "bold");
        doc.text(h.verdict, cols[5], y + 3);

        y += 7;
    });

    // Footer
    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.setTextColor(156, 163, 175);
    doc.text(
        `SurfaceAI Wire Inspection System  |  Session started ${new Date(sessionStart).toLocaleTimeString("en-GB", { hour12: false })}`,
        margin, doc.internal.pageSize.getHeight() - 10
    );

    doc.save(`wireai_session_report_${new Date().toISOString().slice(0, 10)}.pdf`);
}

// ══════════════════════════════════════════════════════════════
//  SETTINGS PAGE
// ══════════════════════════════════════════════════════════════
async function testConnection() {
    const url    = document.getElementById("cfg-apiUrl").value.trim();
    const dotEl  = document.getElementById("dot-conn");
    const textEl = document.getElementById("conn-text");
    textEl.textContent = "Testing…";
    dotEl.className    = "dot amber";
    try {
        const res  = await fetch(`${url}/status`, { signal: AbortSignal.timeout(3000) });
        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        dotEl.className    = "dot green";
        textEl.textContent = `Connected — ${data.model_name} on ${data.device}`;
        API_BASE = url;
    } catch {
        dotEl.className    = "dot red";
        textEl.textContent = "Failed — check the URL and ensure the server is running";
    }
}

document.getElementById("cfg-minConf")?.addEventListener("input", e => {
    MIN_CONF = parseInt(e.target.value);
});

function clearSession() {
    if (!confirm("Clear all session data? This cannot be undone.")) return;
    total = 0; defects = 0; ok = 0;
    counts = { defected_wire: 0, ok_wire: 0 };
    historyLog   = [];
    lastResult   = null;
    sessionStart = Date.now();
    document.getElementById("totalCount").textContent  = "0";
    document.getElementById("defectCount").textContent = "0";
    document.getElementById("okCount").textContent     = "0";
    document.getElementById("defectRate").textContent  = "—";
    document.getElementById("historyList").innerHTML   = '<div class="history-empty">No inspections yet</div>';
    document.getElementById("logCount").textContent    = "0 entries";
    document.getElementById("resultPanel").style.display = "none";
    updateBarChart();
}
