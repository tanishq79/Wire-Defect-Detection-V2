// ══════════════════════════════════════════════════════════════
//  SurfaceAI – Wire Inspection – script.js
// ══════════════════════════════════════════════════════════════

// ── Config ──────────────────────────────────────────────────
const DEFAULT_API_BASE = (window.location.protocol.startsWith("http") && window.location.port !== "8000")
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : window.location.origin;

let API_BASE = DEFAULT_API_BASE || "http://127.0.0.1:8000";
let MIN_CONF = 70; // threshold from settings slider

// ── Session state ────────────────────────────────────────────
let total = 0, defects = 0, ok = 0;
let counts = { defected_wire: 0, ok_wire: 0 };
let historyLog = []; // { prediction, confidence, time, fileName, color, verdict }
let selectedFile = null;
let selectedObjectUrl = null;
let loaderInterval = null;
let sessionStart = Date.now();
let systemInfo = {};
let lastResult = null;
let activeSourceName = "";

// ── Camera & Stream State ────────────────────────────────────
let cameraStream = null;
let currentDeviceId = null;
let isCameraActive = false;
let autoInspectInterval = null;
let isAutoInspectActive = false;
let isCapturing = false;

let tuningState = {
    brightness: 0,
    contrast: 0,
    sharpness: 0,
    mask_strength: 0,
};

// ── Colour / meta map ────────────────────────────────────────
const META = {
    ok_wire: {
        color: "#10b981",
        bg: "rgba(16, 185, 129, 0.15)",
        border: "rgba(16, 185, 129, 0.4)",
        label: "Good Wire (OK)",
        verdict: "PASS",
        action: "Wire accepted. No surface defect detected."
    },
    defected_wire: {
        color: "#ef4444",
        bg: "rgba(239, 68, 68, 0.15)",
        border: "rgba(239, 68, 68, 0.4)",
        label: "Defective Wire",
        verdict: "REJECT",
        action: "Wire rejected. Surface defect detected."
    },
    manual_review: {
        color: "#f59e0b",
        bg: "rgba(245, 158, 11, 0.15)",
        border: "rgba(245, 158, 11, 0.4)",
        label: "Manual Review",
        verdict: "REVIEW",
        action: "Confidence is below operating threshold. Inspect manually."
    },
};

const apiUrlInput = document.getElementById("cfg-apiUrl");
if (apiUrlInput) apiUrlInput.value = API_BASE;

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
    analytics: ["Analytics", "SESSION DATA"],
    reports: ["Reports", "EXPORT READY"],
    settings: ["Settings", "CONFIGURATION"],
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
    setText("pageTitle", title);
    setText("pageTag", tag);

    if (page === "analytics") refreshAnalytics();
    if (page === "reports") refreshReports();
}

// ══════════════════════════════════════════════════════════════
//  CLOCK
// ══════════════════════════════════════════════════════════════
function tick() {
    const time = new Date().toLocaleTimeString("en-GB", { hour12: false });
    setText("clock", time);
    setText("consoleClock", time);
}
tick();
setInterval(tick, 1000);

// ══════════════════════════════════════════════════════════════
//  LIVE STATUS POLL
// ══════════════════════════════════════════════════════════════
async function pollStatus() {
    try {
        const res = await fetch(`${API_BASE}/status`, { signal: AbortSignal.timeout(6000) });
        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        systemInfo = data;

        setDot("dot-model", "green");
        setDot("dot-hud-model", "green");
        setText("status-model", data.model_name + " Active");
        setText("hudModelName", data.model_name + " (" + (data.device || "GPU") + ")");

        setDot("dot-api", "green");
        setText("status-api", "API Connected");

        const beacon = document.getElementById("liveBeacon");
        if (beacon) beacon.style.background = "#10b981";

        if (data.gpu_available) {
            setDot("dot-gpu", "green");
            setText("status-gpu", data.device || "Metal GPU");
        } else {
            setDot("dot-gpu", "amber");
            setText("status-gpu", "CPU Mode");
        }
    } catch {
        setDot("dot-model", "amber");
        setDot("dot-hud-model", "amber");
        setText("status-model", "Connecting…");
        setText("hudModelName", "Model Connecting…");

        setDot("dot-api", "amber");
        setText("status-api", "API Standby");

        const beacon = document.getElementById("liveBeacon");
        if (beacon) beacon.style.background = "#f59e0b";
    }
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function setDot(id, cls) {
    const el = document.getElementById(id);
    if (el) el.className = "dot " + cls;
}

pollStatus();
setInterval(pollStatus, 4000);

// ══════════════════════════════════════════════════════════════
//  LIVE WEBCAM STREAMING (WebRTC / HTML5 MediaDevices)
// ══════════════════════════════════════════════════════════════
async function enumerateCameraDevices() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(d => d.kind === "videoinput");
        const select = document.getElementById("cameraSourceSelect");
        const wrap = document.getElementById("cameraSelectWrap");

        if (videoDevices.length > 1 && select && wrap) {
            wrap.hidden = false;
            select.innerHTML = videoDevices.map((d, i) => `
                <option value="${d.deviceId}" ${d.deviceId === currentDeviceId ? "selected" : ""}>
                    ${d.label || `Camera ${i + 1}`}
                </option>
            `).join("");
        }
    } catch (err) {
        console.warn("Could not enumerate video devices:", err);
    }
}

async function startCameraFeed(deviceId = null) {
    const video = document.getElementById("cameraVideo");
    const preview = document.getElementById("cameraPreview");
    const empty = document.getElementById("cameraEmpty");
    const statusBadge = document.getElementById("cameraStatusBadge");
    const btnCam = document.getElementById("btnCamToggle");

    try {
        if (cameraStream) {
            cameraStream.getTracks().forEach(track => track.stop());
        }

        const constraints = {
            video: {
                deviceId: deviceId ? { exact: deviceId } : undefined,
                width: { ideal: 1920 },
                height: { ideal: 1080 }
            },
            audio: false
        };

        cameraStream = await navigator.mediaDevices.getUserMedia(constraints);
        currentDeviceId = deviceId || (cameraStream.getVideoTracks()[0]?.getSettings()?.deviceId);

        video.srcObject = cameraStream;
        video.style.display = "block";
        preview.style.display = "none";
        empty.style.display = "none";

        isCameraActive = true;
        if (statusBadge) statusBadge.textContent = "LIVE 1080p";
        if (btnCam) btnCam.classList.add("active");

        applyPreviewFilter();
        await enumerateCameraDevices();
    } catch (err) {
        console.error("Camera access error:", err);
        isCameraActive = false;
        if (statusBadge) statusBadge.textContent = "NO CAMERA";
        if (btnCam) btnCam.classList.remove("active");
        alert("Camera access was not granted or no camera is available. You can still upload or drag-and-drop wire images.");
    }
}

function stopCameraFeed() {
    const video = document.getElementById("cameraVideo");
    const empty = document.getElementById("cameraEmpty");
    const statusBadge = document.getElementById("cameraStatusBadge");
    const btnCam = document.getElementById("btnCamToggle");

    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
        cameraStream = null;
    }

    if (video) {
        video.srcObject = null;
        video.style.display = "none";
    }

    if (isAutoInspectActive) {
        toggleAutoInspect();
    }

    isCameraActive = false;
    if (empty) empty.style.display = "flex";
    if (statusBadge) statusBadge.textContent = "STANDBY";
    if (btnCam) btnCam.classList.remove("active");
    setInspectionState("neutral");
}

function toggleCameraFeed() {
    if (isCameraActive) {
        stopCameraFeed();
    } else {
        startCameraFeed(currentDeviceId);
    }
}

function changeCameraSource(deviceId) {
    currentDeviceId = deviceId;
    startCameraFeed(deviceId);
}

// ══════════════════════════════════════════════════════════════
//  CAMERA CAPTURE & SNAPSHOT
// ══════════════════════════════════════════════════════════════
async function captureVideoFrameBase64() {
    const video = document.getElementById("cameraVideo");
    const canvas = document.getElementById("captureCanvas");
    if (!video || !video.videoWidth) return null;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");

    // Apply tuning filter on capture if set
    if (tuningState.brightness !== 0 || tuningState.contrast !== 0) {
        const b = 1 + tuningState.brightness / 100;
        const c = 1 + tuningState.contrast / 100;
        ctx.filter = `brightness(${b}) contrast(${c})`;
    }

    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.92);
}

async function triggerInspectionCapture() {
    if (isCapturing) return;

    markCapturePress(true);

    if (isCameraActive) {
        const base64Data = await captureVideoFrameBase64();
        if (!base64Data) {
            markCapturePress(false);
            return;
        }
        await predictBase64(base64Data);
    } else if (selectedFile) {
        await predict();
    } else {
        markCapturePress(false);
        // If camera is not active, try starting it or prompt user
        startCameraFeed();
    }
}

function toggleAutoInspect() {
    const btn = document.getElementById("btnAutoInspect");
    if (isAutoInspectActive) {
        clearInterval(autoInspectInterval);
        autoInspectInterval = null;
        isAutoInspectActive = false;
        if (btn) btn.classList.remove("active");
    } else {
        if (!isCameraActive) {
            startCameraFeed().then(() => {
                startAutoInspectTimer();
            });
        } else {
            startAutoInspectTimer();
        }
    }
}

function startAutoInspectTimer() {
    const btn = document.getElementById("btnAutoInspect");
    isAutoInspectActive = true;
    if (btn) btn.classList.add("active");
    triggerInspectionCapture();
    autoInspectInterval = setInterval(() => {
        if (isCameraActive && !isCapturing) {
            triggerInspectionCapture();
        }
    }, 1800);
}

// ══════════════════════════════════════════════════════════════
//  FILE HANDLING & DRAG-AND-DROP
// ══════════════════════════════════════════════════════════════
const fileElem = document.getElementById("fileElem");
if (fileElem) {
    fileElem.addEventListener("change", e => {
        if (e.target.files[0]) loadFile(e.target.files[0], true);
        e.target.value = "";
    });
}

function handleDrop(e) {
    e.preventDefault();
    const dropArea = document.getElementById("drop-area");
    if (dropArea) dropArea.classList.remove("drag-over");
    const f = e.dataTransfer.files[0];
    if (f && f.type.startsWith("image/")) loadFile(f, true);
}

// Allow dropping anywhere on the camera frame
const cameraFrameEl = document.getElementById("cameraFrame");
if (cameraFrameEl) {
    cameraFrameEl.addEventListener("dragover", e => e.preventDefault());
    cameraFrameEl.addEventListener("drop", e => {
        e.preventDefault();
        const f = e.dataTransfer.files[0];
        if (f && f.type.startsWith("image/")) loadFile(f, true);
    });
}

function openGalleryUpload() {
    document.getElementById("fileElem")?.click();
}

function loadFile(file, autoInspect = false) {
    selectedFile = file;
    activeSourceName = file.name;
    if (selectedObjectUrl) URL.revokeObjectURL(selectedObjectUrl);
    const objectUrl = URL.createObjectURL(file);
    selectedObjectUrl = objectUrl;

    const previewImg = document.getElementById("previewImage");
    const previewWrap = document.getElementById("previewWrap");
    if (previewImg) previewImg.src = objectUrl;
    if (previewWrap) previewWrap.style.display = "block";

    showUploadedImageInConsole(objectUrl, file.name);
    lastResult = null;

    if (autoInspect) predict();
}

function showUploadedImageInConsole(objectUrl, fileName) {
    const video = document.getElementById("cameraVideo");
    const preview = document.getElementById("cameraPreview");
    const empty = document.getElementById("cameraEmpty");
    const statusBadge = document.getElementById("cameraStatusBadge");

    if (video) video.style.display = "none";
    if (empty) empty.style.display = "none";

    preview.src = objectUrl;
    preview.style.display = "block";

    applyPreviewFilter();
    setInspectionState("neutral");
    setText("cameraStatusBadge", "IMAGE FILE");
    setText("verdictLabel", "IMAGE READY");
    setText("verdictTitle", "Inspecting Image");
    setText("verdictSubtitle", fileName || "Running classification on selected wire image.");
}

// ══════════════════════════════════════════════════════════════
//  TUNING & HUD CONTROLS
// ══════════════════════════════════════════════════════════════
function toggleTuningPanel() {
    const panel = document.getElementById("tuningPanel");
    const btn = document.getElementById("btnTuningToggle");
    if (!panel) return;
    panel.classList.toggle("hidden");
    if (btn) btn.classList.toggle("active", !panel.classList.contains("hidden"));
}

function toggleDrawer(forceState = null) {
    const drawer = document.getElementById("operatorDrawer");
    if (!drawer) return;
    if (forceState !== null) {
        drawer.classList.toggle("open", forceState);
    } else {
        drawer.classList.toggle("open");
    }
}

function applyPreviewFilter() {
    const preview = document.getElementById("cameraPreview");
    const video = document.getElementById("cameraVideo");

    const brightness = 1 + tuningState.brightness / 100;
    const contrast = 1 + tuningState.contrast / 100;
    const sharpness = 1 + tuningState.sharpness / 180;
    const filterVal = `brightness(${brightness}) contrast(${contrast}) saturate(${sharpness})`;

    if (preview) preview.style.filter = filterVal;
    if (video) video.style.filter = filterVal;
}

function updateTuningFromControls() {
    tuningState = {
        brightness: parseInt(document.getElementById("ctlBrightness")?.value || "0", 10),
        contrast: parseInt(document.getElementById("ctlContrast")?.value || "0", 10),
        sharpness: parseInt(document.getElementById("ctlSharpness")?.value || "0", 10),
        mask_strength: parseInt(document.getElementById("ctlMask")?.value || "0", 10),
    };

    setText("valBrightness", tuningState.brightness);
    setText("valContrast", tuningState.contrast);
    setText("valSharpness", tuningState.sharpness);
    setText("valMask", tuningState.mask_strength);

    applyPreviewFilter();
}

function resetTuning() {
    const ids = ["ctlBrightness", "ctlContrast", "ctlSharpness", "ctlMask"];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = 0;
    });
    updateTuningFromControls();
}

function markCapturePress(isActive) {
    const btn = document.getElementById("captureBtn");
    if (!btn) return;
    btn.classList.add("is-pressed");
    setTimeout(() => btn.classList.remove("is-pressed"), 180);
    btn.classList.toggle("is-processing", isActive);
}

// ══════════════════════════════════════════════════════════════
//  LOADER
// ══════════════════════════════════════════════════════════════
function startLoader() {
    const bar = document.getElementById("loaderBar");
    const fill = document.getElementById("loaderFill");
    if (!bar || !fill) return;
    bar.style.display = "block";
    fill.style.width = "0%";
    let w = 0;
    loaderInterval = setInterval(() => {
        w = Math.min(w + Math.random() * 12, 90);
        fill.style.width = w + "%";
    }, 120);
}

function stopLoader() {
    clearInterval(loaderInterval);
    const bar = document.getElementById("loaderBar");
    const fill = document.getElementById("loaderFill");
    if (!fill) return;
    fill.style.width = "100%";
    setTimeout(() => {
        if (bar) bar.style.display = "none";
        fill.style.width = "0%";
    }, 300);
}

// ══════════════════════════════════════════════════════════════
//  PREDICT (File & Base64)
// ══════════════════════════════════════════════════════════════
async function predict() {
    if (!selectedFile) {
        alert("Please upload or capture a wire image first.");
        return;
    }

    isCapturing = true;
    startLoader();

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("brightness", tuningState.brightness);
    formData.append("contrast", tuningState.contrast);
    formData.append("sharpness", tuningState.sharpness);

    try {
        const res = await fetch(`${API_BASE}/predict`, { method: "POST", body: formData });
        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        applyPredictionResult(data, selectedFile.name);
    } catch (err) {
        stopLoader();
        markCapturePress(false);
        isCapturing = false;
        alert(`Inspection failed: ${err.message || "Could not reach the backend API."}`);
        return;
    }

    stopLoader();
    markCapturePress(false);
    isCapturing = false;
}

async function predictBase64(base64Image) {
    isCapturing = true;
    startLoader();

    try {
        const payload = {
            image: base64Image,
            brightness: tuningState.brightness,
            contrast: tuningState.contrast,
            sharpness: tuningState.sharpness,
        };

        const res = await fetch(`${API_BASE}/predict-base64`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error(await readApiError(res));
        const data = await res.json();
        applyPredictionResult(data, "Live Camera Frame");
    } catch (err) {
        stopLoader();
        markCapturePress(false);
        isCapturing = false;
        console.error("Live prediction error:", err);
        return;
    }

    stopLoader();
    markCapturePress(false);
    isCapturing = false;
}

// ══════════════════════════════════════════════════════════════
//  APPLY RESULT & HUD UPDATE
// ══════════════════════════════════════════════════════════════
function applyPredictionResult(data, sourceName) {
    const prediction = data.prediction;
    const confidence = parseFloat(parseFloat(data.confidence).toFixed(1));
    const rawScore = typeof data.raw_score === "number" ? data.raw_score : parseFloat(data.raw_score || "0");
    const goodScore = data.good_score !== undefined ? data.good_score : Math.max(0, Math.min(100, rawScore * 100));
    const defectScore = data.defect_score !== undefined ? data.defect_score : Math.max(0, Math.min(100, (1 - rawScore) * 100));
    const finalPrediction = confidence < MIN_CONF ? "manual_review" : prediction;

    const m = META[finalPrediction] || META.ok_wire;
    const timeStr = new Date().toLocaleTimeString("en-GB", { hour12: false });
    const dateStr = new Date().toLocaleDateString("en-CA");
    const fileName = sourceName || activeSourceName || "live_camera_capture";

    // ── Update Floating Verdict HUD Card ───────────────────────
    updateVerdictHUD(finalPrediction, confidence, goodScore, defectScore, m);

    // ── Update Drawer Details ──────────────────────────────────
    const resultPanel = document.getElementById("resultPanel");
    if (resultPanel) resultPanel.style.display = "block";

    const badge = document.getElementById("resultBadge");
    if (badge) {
        badge.textContent = m.label;
        badge.style.color = m.color;
    }

    setText("confidenceText", confidence + "%");
    const fill = document.getElementById("confidenceFill");
    if (fill) {
        fill.style.width = confidence + "%";
        fill.style.background = m.color;
    }

    setText("actionText", m.action);

    // ── Save last result for PDF ───────────────────────────────
    lastResult = {
        prediction: finalPrediction,
        confidence,
        timeStr,
        dateStr,
        fileName,
        verdict: m.verdict,
        label: m.label
    };

    // ── Session counters ───────────────────────────────────────
    total++;
    counts[prediction]++;
    if (prediction === "ok_wire") ok++;
    else defects++;

    setText("totalCount", total);
    setText("okCount", ok);
    setText("defectCount", defects);
    const rate = total > 0 ? ((defects / total) * 100).toFixed(0) + "%" : "0%";
    setText("defectRate", rate);

    // ── History & Charts ───────────────────────────────────────
    historyLog.unshift({
        prediction,
        classLabel: m.label,
        confidence,
        time: timeStr,
        date: dateStr,
        fileName,
        color: m.color,
        verdict: m.verdict
    });

    renderHistory();
    updateBarChart();
}

function setInspectionState(state) {
    const frame = document.getElementById("cameraFrame");
    if (frame) {
        frame.classList.remove("state-neutral", "state-good", "state-review", "state-bad");
        frame.classList.add(`state-${state}`);
    }
}

function updateVerdictHUD(prediction, confidence, goodScore, defectScore, m) {
    const stateMap = {
        ok_wire: "good",
        defected_wire: "bad",
        manual_review: "review",
    };
    const state = stateMap[prediction] || "neutral";
    setInspectionState(state);

    const verdictLabel = document.getElementById("verdictLabel");
    if (verdictLabel) {
        verdictLabel.textContent = m.verdict;
        verdictLabel.style.color = m.color;
        verdictLabel.style.background = m.bg;
    }

    setText("verdictConfVal", confidence + "%");
    setText("verdictTitle", m.label);
    setText("verdictSubtitle", m.action);

    const barFill = document.getElementById("verdictBarFill");
    if (barFill) {
        barFill.style.width = confidence + "%";
        barFill.style.background = m.color;
    }

    setText("scoreGood", typeof goodScore === "number" ? goodScore.toFixed(1) + "%" : goodScore + "%");
    setText("scoreDefect", typeof defectScore === "number" ? defectScore.toFixed(1) + "%" : defectScore + "%");
}

// ── Keyboard shortcuts: Space / Enter to inspect, C to toggle camera ──
window.addEventListener("keydown", e => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;

    if (e.code === "Space" || e.key === "Enter") {
        e.preventDefault();
        triggerInspectionCapture();
    } else if (e.key === "c" || e.key === "C") {
        toggleCameraFeed();
    } else if (e.key === "u" || e.key === "U") {
        openGalleryUpload();
    }
});


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
function fitPdfText(doc, text, maxWidth) {
    const clean = String(text || "-").replace(/\s+/g, " ");
    if (doc.getTextWidth(clean) <= maxWidth) return clean;

    const normalized = clean.replace(/\\/g, "/");
    const filename = normalized.split("/").filter(Boolean).pop() || clean;
    const candidate = filename.length < clean.length ? ".../" + filename : clean;
    if (doc.getTextWidth(candidate) <= maxWidth) return candidate;

    let trimmed = candidate;
    while (trimmed.length > 4 && doc.getTextWidth(trimmed + "...") > maxWidth) {
        trimmed = trimmed.slice(0, -1);
    }
    return trimmed.length > 4 ? trimmed + "..." : "...";
}

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
    const cols = [margin, margin + 10, margin + 60, margin + 88, margin + 145, margin + 166];
    const fileMaxWidth = cols[4] - cols[3] - 5;
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
        const fn = fitPdfText(doc, h.fileName || "-", fileMaxWidth);
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
        const res  = await fetch(`${url}/status`, { signal: AbortSignal.timeout(8000) });
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

["ctlBrightness", "ctlContrast", "ctlSharpness", "ctlMask"].forEach(id => {
    document.getElementById(id)?.addEventListener("input", updateTuningFromControls);
    document.getElementById(id)?.addEventListener("change", updateTuningFromControls);
});

updateTuningFromControls();

function clearSession() {
    if (!confirm("Clear all session data? This cannot be undone.")) return;
    total = 0; defects = 0; ok = 0;
    counts = { defected_wire: 0, ok_wire: 0 };
    historyLog = [];
    lastResult = null;
    sessionStart = Date.now();
    setText("totalCount", "0");
    setText("defectCount", "0");
    setText("okCount", "0");
    setText("defectRate", "0%");
    setText("drawerBadgeCount", "0");
    
    const histList = document.getElementById("historyList");
    if (histList) histList.innerHTML = '<div class="history-empty">No inspections yet</div>';
    
    setText("logCount", "0 entries");
    const resPanel = document.getElementById("resultPanel");
    if (resPanel) resPanel.style.display = "none";
    
    updateBarChart();
    setInspectionState("neutral");
    setText("verdictLabel", "READY");
    setText("verdictTitle", "Awaiting Inspection");
    setText("verdictSubtitle", "Place wire in alignment box and capture.");
    setText("verdictConfVal", "--%");
    setText("scoreGood", "--%");
    setText("scoreDefect", "--%");
    const fill = document.getElementById("verdictBarFill");
    if (fill) fill.style.width = "0%";
}

// ── Startup Initialization ────────────────────────────────────
setInspectionState("neutral");
updateTuningFromControls();

// Try starting the live camera feed on load
setTimeout(() => {
    startCameraFeed();
}, 400);