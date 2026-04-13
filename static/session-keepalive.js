(function () {
    const REFRESH_WINDOW_MS = 10 * 60 * 1000;
    const REFRESH_THROTTLE_MS = 5 * 60 * 1000;
    const ACTIVITY_CHECK_MS = 60 * 1000;
    const ACTIVE_WINDOW_MS = 2 * 60 * 1000;

    let lastRefreshAt = 0;
    let lastActivityAt = Date.now();
    let refreshInFlight = false;

    function decodeJwtPayload(token) {
        try {
            const payload = token.split(".")[1];
            return JSON.parse(atob(payload));
        } catch (error) {
            return null;
        }
    }

    function isAdminToken(token) {
        const payload = decodeJwtPayload(token);
        return !!(payload && payload.is_admin);
    }

    function getStoredToken() {
        const adminToken = localStorage.getItem("admin_token");
        const studentToken = localStorage.getItem("token");
        const currentPath = (window.location.pathname || "").toLowerCase();

        if (currentPath.startsWith("/admin")) {
            return adminToken;
        }

        if (currentPath.startsWith("/student")) {
            if (studentToken) return studentToken;
            return adminToken && !isAdminToken(adminToken) ? adminToken : null;
        }

        return adminToken || studentToken;
    }

    function getTokenExpiryMs(token) {
        const payload = decodeJwtPayload(token);
        return payload && payload.exp ? payload.exp * 1000 : null;
    }

    function persistToken(newToken) {
        if (isAdminToken(newToken)) {
            localStorage.setItem("admin_token", newToken);
            document.cookie = `admin_access_token=${newToken}; path=/; max-age=86400; SameSite=Strict`;
            return;
        }

        localStorage.setItem("token", newToken);
        document.cookie = "admin_access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";

        const existingAdminToken = localStorage.getItem("admin_token");
        if (existingAdminToken && !isAdminToken(existingAdminToken)) {
            localStorage.removeItem("admin_token");
        }
    }

    async function refreshSession(force) {
        const token = getStoredToken();
        if (!token || refreshInFlight) return;

        const now = Date.now();
        const expiresAt = getTokenExpiryMs(token);
        const isExpiringSoon = expiresAt ? (expiresAt - now) <= REFRESH_WINDOW_MS : true;
        const isThrottled = (now - lastRefreshAt) < REFRESH_THROTTLE_MS;

        if (!force && !isExpiringSoon && isThrottled) {
            return;
        }

        refreshInFlight = true;

        try {
            const response = await fetch("/auth/refresh", {
                method: "POST",
                headers: {
                    "Authorization": `Bearer ${token}`
                }
            });

            if (response.status === 401) {
                return;
            }

            if (!response.ok) {
                throw new Error("Failed to refresh session");
            }

            const data = await response.json();
            if (data.access_token) {
                persistToken(data.access_token);
                lastRefreshAt = Date.now();
            }
        } catch (error) {
            console.error("Session keep-alive failed:", error);
        } finally {
            refreshInFlight = false;
        }
    }

    function recordActivity() {
        lastActivityAt = Date.now();
        refreshSession(false);
    }

    function initializeSessionKeepAlive() {
        if (!getStoredToken()) return;

        ["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((eventName) => {
            window.addEventListener(eventName, recordActivity, { passive: true });
        });

        setInterval(() => {
            if (Date.now() - lastActivityAt <= ACTIVE_WINDOW_MS) {
                refreshSession(false);
            }
        }, ACTIVITY_CHECK_MS);
    }

    initializeSessionKeepAlive();
})();
