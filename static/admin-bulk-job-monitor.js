(function () {
    const STORAGE_KEY = "active_bulk_registration_job_id";
    const POLL_INTERVAL_MS = 1000;
    let poller = null;

    function getJobId() {
        return localStorage.getItem(STORAGE_KEY);
    }

    function clearJobId() {
        localStorage.removeItem(STORAGE_KEY);
    }

    function ensureBanner() {
        if (!document.getElementById("adminBulkJobProgressStyle")) {
            const style = document.createElement("style");
            style.id = "adminBulkJobProgressStyle";
            style.textContent = "@keyframes bulkProgressFlow{from{background-position:0 0}to{background-position:220% 0}}";
            document.head.appendChild(style);
        }

        let banner = document.getElementById("adminBulkJobBanner");
        if (banner) return banner;

        banner = document.createElement("div");
        banner.id = "adminBulkJobBanner";
        banner.style.cssText = [
            "display:none",
            "position:fixed",
            "right:20px",
            "bottom:20px",
            "width:320px",
            "padding:16px",
            "border-radius:16px",
            "background:linear-gradient(135deg,#0f2f57,#1e4f86)",
            "color:#fff",
            "box-shadow:0 14px 34px rgba(0,51,102,.22)",
            "z-index:9999",
            "font-family:Montserrat,sans-serif"
        ].join(";");

        banner.innerHTML = `
            <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start;">
                <div>
                    <div id="adminBulkJobBannerTitle" style="font-size:15px; font-weight:700;">Registration in progress</div>
                    <div id="adminBulkJobBannerMessage" style="margin-top:4px; font-size:12px; opacity:.92;">Processing users in the background.</div>
                </div>
                <button id="adminBulkJobBannerDismiss" type="button" style="background:transparent; border:none; color:#fff; font-size:18px; cursor:pointer; line-height:1;">×</button>
            </div>
            <div style="margin-top:12px; height:10px; border-radius:999px; background:rgba(255,255,255,.18); overflow:hidden;">
            <div id="adminBulkJobBannerProgress" style="width:0%; height:100%; background:linear-gradient(90deg,#f7b500 0%,#ffd95a 35%,#fff3b0 55%,#ffd95a 75%,#f7b500 100%); background-size:220% 100%; animation:bulkProgressFlow 1.05s linear infinite; transition:width 1.15s linear;"></div>
            </div>
            <div id="adminBulkJobBannerMeta" style="margin-top:10px; font-size:12px; opacity:.92;">Preparing background registration...</div>
            <div style="margin-top:12px; display:flex; justify-content:flex-end; gap:8px;">
                <button id="adminBulkJobBannerOpen" type="button" style="display:none; border:none; border-radius:999px; padding:8px 14px; background:#ffd95a; color:#0f2f57; font-weight:700; cursor:pointer;">Open User Management</button>
            </div>
        `;

        document.body.appendChild(banner);

        document.getElementById("adminBulkJobBannerDismiss")?.addEventListener("click", () => {
            clearJobId();
            hideBanner();
            stopPolling();
        });

        document.getElementById("adminBulkJobBannerOpen")?.addEventListener("click", () => {
            window.location.href = "/admin/User-Management?tab=student";
        });

        return banner;
    }

    function hideBanner() {
        const banner = document.getElementById("adminBulkJobBanner");
        if (banner) banner.style.display = "none";
    }

    function renderBanner(job) {
    const banner = ensureBanner();
    const title = document.getElementById("adminBulkJobBannerTitle");
    const message = document.getElementById("adminBulkJobBannerMessage");
    const meta = document.getElementById("adminBulkJobBannerMeta");
    const progress = document.getElementById("adminBulkJobBannerProgress");
    const openBtn = document.getElementById("adminBulkJobBannerOpen");

    if (!banner || !title || !message || !meta || !progress || !openBtn) return;

    const summary = job.summary || {};
    const processed = Number(job.processed || 0);
    const total = Number(job.total || 0);
    const rawProgress = Number(job.progress || 0);

    const derivedProgress = total > 0 ? Math.round((processed / total) * 100) : 0;
    const visibleProgress =
        (job.status === "queued" || job.status === "running")
            ? Math.max(rawProgress, derivedProgress, 2)
            : Math.max(rawProgress, derivedProgress);

    banner.style.display = "block";
    progress.style.width = `${visibleProgress}%`;

    if (job.status === "completed") {
        title.innerText = "Registration completed";
        message.innerText = "The background registration finished successfully.";
        meta.innerText = `Processed ${processed}/${total}. Created: ${summary.created || 0} | Replaced: ${summary.replaced || 0} | Ignored: ${summary.ignored || 0}`;
        progress.style.background = "linear-gradient(90deg,#16a34a,#22c55e)";
        progress.style.animation = "none";
        openBtn.style.display = "inline-flex";
        stopPolling();

        if (window.location.pathname === "/admin/User-Management" && typeof loadUsers === "function") {
            loadUsers("student");
        }
        return;
    }

    if (job.status === "failed") {
        title.innerText = "Registration failed";
        message.innerText = job.error || job.message || "The background registration stopped before finishing.";
        meta.innerText = `Processed ${processed}/${total} students before it stopped.`;
        progress.style.animation = "none";
        openBtn.style.display = "inline-flex";
        stopPolling();
        return;
    }

    title.innerText = job.status === "queued"
        ? "Registration queued"
        : "Registration in progress";
    progress.style.animation = "bulkProgressFlow 1.05s linear infinite";

    if (processed < 10) {
        message.innerText = "Preparing users and securing passwords. Please wait...";
    } else {
        message.innerText = job.message || "Processing users in the background while you keep using the system.";
    }

    meta.innerText = `Processed ${processed}/${total}. Created: ${summary.created || 0} | Replaced: ${summary.replaced || 0} | Ignored: ${summary.ignored || 0}`;
    openBtn.style.display = window.location.pathname === "/admin/User-Management" ? "none" : "inline-flex";
}

    async function pollJobStatus() {
        const token = sessionStorage.getItem("admin_token");
        const jobId = getJobId();

        if (!token || !jobId) {
            hideBanner();
            stopPolling();
            return;
        }

        try {
            const response = await fetch(`/admin/bulk-register-students/status/${jobId}`, {
                headers: { "Authorization": `Bearer ${token}` }
            });

            const job = await response.json();

            if (!response.ok) {
                if (response.status === 404) {
                    console.warn("Old bulk job no longer exists. Clearing...");
                    clearJobId();
                    hideBanner();
                    stopPolling();
                    return;
                }

                throw new Error(job.detail || "Failed to fetch bulk registration status.");
            }

            renderBanner(job);

        } catch (error) {
            console.error("Cross-page bulk registration polling failed:", error);
            clearJobId();
            hideBanner();
            stopPolling();
        }
    }

    function stopPolling() {
        if (poller) {
            clearInterval(poller);
            poller = null;
        }
    }

    function startPolling() {
    // User Management has its own detailed progress card and poller.
    if (window.location.pathname.toLowerCase() === "/admin/user-management") {
        stopPolling();
        hideBanner();
        return;
    }
    if (!getJobId() || !sessionStorage.getItem("admin_token")) return;

    if (poller) clearInterval(poller);

    // Show banner immediately before first backend response
    const banner = ensureBanner();
    const title = document.getElementById("adminBulkJobBannerTitle");
    const message = document.getElementById("adminBulkJobBannerMessage");
    const meta = document.getElementById("adminBulkJobBannerMeta");
    const progress = document.getElementById("adminBulkJobBannerProgress");
    const openBtn = document.getElementById("adminBulkJobBannerOpen");

    if (banner) banner.style.display = "block";
    if (title) title.innerText = "Registration starting...";
    if (message) message.innerText = "Preparing background registration...";
    if (meta) meta.innerText = "Connecting to upload service...";
    if (progress) progress.style.width = "1%";
    if (openBtn) openBtn.style.display = "none";

    pollJobStatus();
    poller = setInterval(pollJobStatus, POLL_INTERVAL_MS);
}

    startPolling();
    window.addEventListener("pageshow", startPolling);
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            startPolling();
        }
    });
})();
