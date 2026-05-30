(function () {
    const REFRESH_WINDOW_MS = 10 * 60 * 1000;
    const REFRESH_THROTTLE_MS = 5 * 60 * 1000;
    const ACTIVITY_CHECK_MS = 60 * 1000;
    const ACTIVE_WINDOW_MS = 2 * 60 * 1000;

    let lastRefreshAt = 0;
    let lastActivityAt = Date.now();
    let refreshInFlight = false;
    const ROOT_ADMIN_EMAIL = "admin@novaliches.sti.edu.ph";
    const ADMIN_PERMISSION_KEYS = [
        "Messages",
        "User-Management",
        "User-Management-Create",
        "User-Management-Edit",
        "User-Management-Reset",
        "User-Management-Archive",
        "User-Management-Delete",
        "Lost-Reports",
        "Found-Reports",
        "Claim-Management",
        "Reports",
        "Confiscated-items",
        "Content-management"
    ];

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

    function isRootAdminToken(token) {
        const payload = decodeJwtPayload(token);
        return !!(
            payload
            && payload.is_admin
            && String(payload.sub || "").trim().toLowerCase() === ROOT_ADMIN_EMAIL
        );
    }

    function getStoredToken() {
        const adminToken = sessionStorage.getItem("admin_token");
        const studentToken = localStorage.getItem("token");
        const currentPath = (window.location.pathname || "").toLowerCase();

        if (currentPath.startsWith("/admin")) {
            return adminToken;
        }

        if (currentPath.startsWith("/student")) {
            return studentToken;
        }

        return adminToken || studentToken;
    }

    function getTokenExpiryMs(token) {
        const payload = decodeJwtPayload(token);
        return payload && payload.exp ? payload.exp * 1000 : null;
    }

    function persistToken(newToken) {
        if (isAdminToken(newToken)) {
            sessionStorage.setItem("admin_token", newToken);
            localStorage.removeItem("admin_token");
            document.cookie = "admin_access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
            preloadAdminPermissions();
            return;
        }

        localStorage.setItem("token", newToken);
        document.cookie = "admin_access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";

        const existingAdminToken = sessionStorage.getItem("admin_token");
        if (existingAdminToken && !isAdminToken(existingAdminToken)) {
            sessionStorage.removeItem("admin_token");
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

    function getAdminPermissionsCacheKey(token) {
        const payload = decodeJwtPayload(token);
        const userKey = payload?.id || payload?.sub || "admin";
        return `admin_permissions:${userKey}`;
    }

    function readCachedAdminPermissions(token) {
        if (!token) return null;
        if (isRootAdminToken(token)) return ADMIN_PERMISSION_KEYS;

        try {
            const raw = sessionStorage.getItem(getAdminPermissionsCacheKey(token));
            const cached = raw ? JSON.parse(raw) : null;
            return Array.isArray(cached) ? cached : null;
        } catch (error) {
            return null;
        }
    }

    function writeCachedAdminPermissions(token, permissions) {
        if (!token || !Array.isArray(permissions)) return;
        sessionStorage.setItem(
            getAdminPermissionsCacheKey(token),
            JSON.stringify(permissions)
        );
    }

    async function getAdminPermissions(forceRefresh) {
        const token = sessionStorage.getItem("admin_token");
        if (!token) return [];

        const cached = readCachedAdminPermissions(token);
        if (!forceRefresh && cached) return cached;

        if (isRootAdminToken(token)) {
            writeCachedAdminPermissions(token, ADMIN_PERMISSION_KEYS);
            return ADMIN_PERMISSION_KEYS;
        }

        const response = await fetch("/admin/my-permissions", {
            headers: { "Authorization": `Bearer ${token}` }
        });

        if (!response.ok) throw new Error("Unauthorized");

        const permissions = await response.json();
        const normalized = Array.isArray(permissions) ? permissions : [];
        writeCachedAdminPermissions(token, normalized);
        return normalized;
    }

    function preloadAdminPermissions() {
        const currentPath = (window.location.pathname || "").toLowerCase();
        if (!currentPath.startsWith("/admin")) return;
        getAdminPermissions(false).catch((error) => {
            console.error("Admin permission preload failed:", error);
        });
    }

    function normalizeProfilePicUrl(profilePic) {
        const fallback = "/static/photos/default-student-avatar.jpg";
        if (!profilePic) return fallback;

        const normalized = String(profilePic).replace(/\\/g, "/");
        const url = normalized.startsWith("/") ? normalized : `/${normalized}`;
        const separator = url.includes("?") ? "&" : "?";
        return `${url}${separator}t=${Date.now()}`;
    }

    async function loadTopbarProfileAvatar() {
        const avatars = document.querySelectorAll(".topbar-profile-pic");
        if (!avatars.length) return;

        const token = getStoredToken();
        if (!token) return;

        try {
            const response = await fetch("/api/current-user", {
                headers: { "Authorization": `Bearer ${token}` }
            });

            if (!response.ok) return;

            const user = await response.json();
            const profilePicUrl = normalizeProfilePicUrl(user.profile_pic);

            avatars.forEach((avatar) => {
                avatar.style.width = "38px";
                avatar.style.height = "38px";
                avatar.style.minWidth = "38px";
                avatar.style.maxWidth = "38px";
                avatar.style.minHeight = "38px";
                avatar.style.maxHeight = "38px";
                avatar.style.borderRadius = "50%";
                avatar.style.objectFit = "cover";
                avatar.style.display = "block";
                avatar.onerror = () => {
                    avatar.onerror = null;
                    avatar.src = "/static/photos/default-student-avatar.jpg";
                };
                avatar.src = profilePicUrl;
            });
        } catch (error) {
            console.error("Topbar profile avatar load failed:", error);
        }
    }

    async function cachedCheckAccess(targetUrl, permission) {
        const token = sessionStorage.getItem("admin_token");

        if (!token) {
            window.location.href = "/";
            return;
        }

        try {
            const permissions = await getAdminPermissions(false);
            if (permissions.includes(permission)) {
                window.location.href = targetUrl;
            } else if (typeof window.showAccessDeniedPopup === "function") {
                window.showAccessDeniedPopup(permission);
            }
        } catch (error) {
            console.error("Access check failed:", error);
            if (typeof window.showAccessDeniedPopup === "function") {
                window.showAccessDeniedPopup(permission);
            }
        }
    }

    window.getAdminPermissionsCached = getAdminPermissions;
    window.checkAccess = cachedCheckAccess;

    initializeSessionKeepAlive();
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", preloadAdminPermissions, { once: true });
        document.addEventListener("DOMContentLoaded", loadTopbarProfileAvatar, { once: true });
    } else {
        preloadAdminPermissions();
        loadTopbarProfileAvatar();
    }
})();
