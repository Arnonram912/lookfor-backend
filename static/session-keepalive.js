(function () {
    const IDLE_TIMEOUT_MS = 15 * 60 * 1000;
    const REFRESH_WINDOW_MS = 10 * 60 * 1000;
    const REFRESH_THROTTLE_MS = 5 * 60 * 1000;
    const ACTIVITY_CHECK_MS = 60 * 1000;
    const ACTIVE_WINDOW_MS = 2 * 60 * 1000;
    const LAST_ACTIVITY_KEY = "lookfor_last_activity_at";

    let lastRefreshAt = 0;
    let lastActivityAt = Date.now();
    let refreshInFlight = false;
    let idleTimeoutId = null;
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

    function getLastActivityAt() {
        const stored = Number(localStorage.getItem(LAST_ACTIVITY_KEY));
        return Number.isFinite(stored) && stored > 0 ? stored : lastActivityAt;
    }

    function persistLastActivity(timestamp) {
        lastActivityAt = timestamp;
        localStorage.setItem(LAST_ACTIVITY_KEY, String(timestamp));
    }

    function expireSession() {
        sessionStorage.clear();
        localStorage.removeItem("token");
        localStorage.removeItem("admin_token");
        localStorage.removeItem(LAST_ACTIVITY_KEY);
        document.cookie = "admin_access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
        window.location.replace("/login");
    }

    function isIdleTimedOut() {
        return Date.now() - getLastActivityAt() >= IDLE_TIMEOUT_MS;
    }

    function scheduleIdleTimeout() {
        if (idleTimeoutId) {
            clearTimeout(idleTimeoutId);
        }

        const remainingMs = Math.max(0, IDLE_TIMEOUT_MS - (Date.now() - getLastActivityAt()));
        idleTimeoutId = setTimeout(expireSession, remainingMs);
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
                expireSession();
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
        if (isIdleTimedOut()) {
            expireSession();
            return;
        }

        persistLastActivity(Date.now());
        scheduleIdleTimeout();
        refreshSession(false);
    }

    function initializeSessionKeepAlive() {
        if (!getStoredToken()) return;

        if (isIdleTimedOut()) {
            expireSession();
            return;
        }

        persistLastActivity(Date.now());
        scheduleIdleTimeout();

        ["mousemove", "keydown", "click", "scroll", "touchstart"].forEach((eventName) => {
            window.addEventListener(eventName, recordActivity, { passive: true });
        });

        setInterval(() => {
            if (isIdleTimedOut()) {
                expireSession();
                return;
            }

            if (Date.now() - getLastActivityAt() <= ACTIVE_WINDOW_MS) {
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
                avatar.style.width = "34px";
                avatar.style.height = "34px";
                avatar.style.minWidth = "34px";
                avatar.style.maxWidth = "34px";
                avatar.style.minHeight = "34px";
                avatar.style.maxHeight = "34px";
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

    function addAdminSidebarMenuItems() {
        const nav = document.querySelector("body > .sidebar .nav-links");
        if (!nav) return;
        const adminPageAliases = {
            "/admin/For-Disposal": "/c/9374b372-d94f-5fa4-a36d-e219bd12e3a6",
            "/admin/Audit-Logs": "/c/3fbf5fb3-92b4-57c5-81ac-8e82ef0bce83",
            "/admin/Confiscated-items": "/c/dd5c6fcb-8cb9-54c8-bb07-d8b3f6e2aa79",
            "/admin/Reports": "/c/8c2dc56e-79ae-5939-890e-315c8a959b32"
        };

        function isAdminSubpageActive(targetUrl) {
            const target = new URL(targetUrl, window.location.origin);
            const current = new URL(window.location.href);
            const currentPath = current.pathname.toLowerCase();
            const targetPath = target.pathname.toLowerCase();
            const aliasPath = (adminPageAliases[target.pathname] || "").toLowerCase();

            if (targetPath === "/admin/for-disposal") {
                return (
                    currentPath === targetPath
                    || currentPath === aliasPath
                    || (
                        (currentPath === "/admin/confiscated-items"
                            || currentPath === (adminPageAliases["/admin/Confiscated-items"] || "").toLowerCase())
                        && current.searchParams.get("view") === "disposal"
                    )
                );
            }

            if (targetPath === "/admin/audit-logs") {
                return (
                    currentPath === targetPath
                    || currentPath === aliasPath
                    || (
                        (currentPath === "/admin/reports"
                            || currentPath === (adminPageAliases["/admin/Reports"] || "").toLowerCase())
                        && current.searchParams.get("view") === "audit"
                    )
                );
            }

            return (
                currentPath === targetPath
                || Boolean(aliasPath && currentPath === aliasPath)
            );
        }

        function insertAfterLink(matchPath, id, label, targetUrl, permission, iconPath) {
            const parentLink = Array.from(nav.querySelectorAll("a")).find(link =>
                String(link.getAttribute("onclick") || link.getAttribute("href") || "")
                    .toLowerCase()
                    .includes(matchPath.toLowerCase())
            );
            if (!parentLink?.closest("li")) return;

            let item = document.getElementById(id);
            if (!item) {
                item = document.createElement("li");
                item.id = id;
                item.dataset.permission = permission;
                item.innerHTML = `
                    <a href="#" aria-label="${label}">
                        <img src="${iconPath}" class="side-icon" alt=""> ${label}
                    </a>
                `;
                item.querySelector("a").addEventListener("click", event => {
                    event.preventDefault();
                    cachedCheckAccess(targetUrl, permission);
                });
                parentLink.closest("li").insertAdjacentElement("afterend", item);
            }

            if (isAdminSubpageActive(targetUrl)) {
                const parentItem = parentLink.closest("li");
                parentItem.classList.remove("active");
                parentItem.removeAttribute("style");
                item.classList.add("active");
                item.removeAttribute("style");
                item.querySelector("a").removeAttribute("style");
            }
        }

        insertAfterLink(
            "/admin/confiscated-items",
            "adminForDisposalNav",
            "For Disposal",
            "/admin/For-Disposal",
            "Confiscated-items",
            "/static/photos/handw.png"
        );
        insertAfterLink(
            "/admin/reports",
            "adminAuditLogsNav",
            "Audit Logs",
            "/admin/Audit-Logs",
            "Reports",
            "/static/photos/folderw.png"
        );

        // Some legacy page scripts mark their parent menu active after DOMContentLoaded.
        // Re-apply the query-specific submenu state after those handlers finish.
        if (!addAdminSidebarMenuItems.activeStateQueued) {
            addAdminSidebarMenuItems.activeStateQueued = true;
            window.setTimeout(() => {
                addAdminSidebarMenuItems();
            }, 0);
        }
    }

    initializeSessionKeepAlive();
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", preloadAdminPermissions, { once: true });
        document.addEventListener("DOMContentLoaded", loadTopbarProfileAvatar, { once: true });
        document.addEventListener("DOMContentLoaded", addAdminSidebarMenuItems, { once: true });
    } else {
        preloadAdminPermissions();
        loadTopbarProfileAvatar();
        addAdminSidebarMenuItems();
    }
})();
