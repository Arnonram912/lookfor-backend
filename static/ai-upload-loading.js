(function () {
    const uploadPaths = new Set([
        "/admin/items/lost",
        "/admin/items/founds",
        "/student/items/lost/report",
        "/student/found",
        "/api/lost-report-upload",
        "/api/save-found-item",
    ]);
    const messages = [
        "Uploading your report…",
        "AI is comparing the item image and details…",
        "Checking category, brand, color, location, and time…",
        "Saving the closest possible matches…",
    ];
    let activeRequests = 0;
    let messageTimer = null;

    function ensureOverlay() {
        let overlay = document.getElementById("aiUploadLoadingOverlay");
        if (overlay) return overlay;

        const style = document.createElement("style");
        style.textContent = `
            #aiUploadLoadingOverlay {
                position: fixed; inset: 0; z-index: 2147483647;
                display: none; align-items: center; justify-content: center;
                padding: 24px; background: rgba(8, 26, 45, .66);
                backdrop-filter: blur(3px);
            }
            #aiUploadLoadingOverlay.ai-upload-visible { display: flex; }
            .ai-upload-card {
                width: min(420px, 100%); padding: 30px 26px;
                border-radius: 18px; background: #fff; color: #13263a;
                text-align: center; box-shadow: 0 24px 70px rgba(0,0,0,.28);
                font-family: Arial, sans-serif;
            }
            .ai-upload-spinner {
                width: 52px; height: 52px; margin: 0 auto 20px;
                border: 5px solid #dbe8f4; border-top-color: #07589b;
                border-radius: 50%; animation: aiUploadSpin .85s linear infinite;
            }
            .ai-upload-title { margin: 0 0 10px; font-size: 21px; font-weight: 750; }
            .ai-upload-message { min-height: 44px; margin: 0; color: #526579; line-height: 1.45; }
            .ai-upload-note { margin: 16px 0 0; color: #718096; font-size: 12px; }
            @keyframes aiUploadSpin { to { transform: rotate(360deg); } }
            @media (prefers-reduced-motion: reduce) {
                .ai-upload-spinner { animation-duration: 1.8s; }
            }
        `;
        document.head.appendChild(style);

        overlay = document.createElement("div");
        overlay.id = "aiUploadLoadingOverlay";
        overlay.setAttribute("role", "status");
        overlay.setAttribute("aria-live", "polite");
        overlay.setAttribute("aria-busy", "true");
        overlay.innerHTML = `
            <div class="ai-upload-card">
                <div class="ai-upload-spinner" aria-hidden="true"></div>
                <h2 class="ai-upload-title">Processing report</h2>
                <p class="ai-upload-message" id="aiUploadLoadingMessage">${messages[0]}</p>
                <p class="ai-upload-note">Please keep this page open. The page is still responsive.</p>
            </div>
        `;
        document.body.appendChild(overlay);
        return overlay;
    }

    function showLoading() {
        activeRequests += 1;
        const overlay = ensureOverlay();
        const message = overlay.querySelector("#aiUploadLoadingMessage");
        let messageIndex = 0;
        message.textContent = messages[messageIndex];
        overlay.classList.add("ai-upload-visible");
        document.body.setAttribute("aria-busy", "true");
        if (!messageTimer) {
            messageTimer = window.setInterval(function () {
                messageIndex = Math.min(messageIndex + 1, messages.length - 1);
                message.textContent = messages[messageIndex];
                if (messageIndex === messages.length - 1) {
                    window.clearInterval(messageTimer);
                    messageTimer = null;
                }
            }, 2500);
        }
    }

    function hideLoading() {
        activeRequests = Math.max(0, activeRequests - 1);
        if (activeRequests) return;
        if (messageTimer) window.clearInterval(messageTimer);
        messageTimer = null;
        const overlay = document.getElementById("aiUploadLoadingOverlay");
        if (overlay) overlay.classList.remove("ai-upload-visible");
        document.body.removeAttribute("aria-busy");
    }

    function isReportUpload(input, init) {
        const method = String((init && init.method) || "GET").toUpperCase();
        if (method !== "POST") return false;
        const rawUrl = typeof input === "string" ? input : input && input.url;
        if (!rawUrl) return false;
        try {
            return uploadPaths.has(new URL(rawUrl, window.location.href).pathname);
        } catch (_) {
            return false;
        }
    }

    const nativeFetch = window.fetch.bind(window);
    window.fetch = async function (input, init) {
        const show = isReportUpload(input, init);
        if (show) showLoading();
        try {
            return await nativeFetch(input, init);
        } finally {
            if (show) hideLoading();
        }
    };
})();
