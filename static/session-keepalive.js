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
        "Dashboard",
        "Messages",
        "Messages-Send",
        "Messages-Manage",
        "User-Management",
        "User-Management-Create",
        "User-Management-Edit",
        "User-Management-Reset",
        "User-Management-Archive",
        "User-Management-Delete",
        "Lost-Reports",
        "Lost-Reports-Create",
        "Lost-Reports-Archive",
        "Lost-Reports-Delete",
        "Found-Reports",
        "Found-Reports-Create",
        "Found-Reports-Approve",
        "Found-Reports-Archive",
        "Found-Reports-Delete",
        "Claim-Management",
        "Claim-Management-Create",
        "Claim-Management-Decide",
        "Reports",
        "Reports-Export",
        "Reports-Manage",
        "Confiscated-items",
        "Confiscated-items-Create",
        "Confiscated-items-Edit",
        "Confiscated-items-Delete",
        "For-Disposal",
        "For-Disposal-Manage",
        "Audit-Logs",
        "Content-management",
        "Content-management-Announcements",
        "Content-management-Taxonomy",
        "Content-management-Term",
        "Content-management-Edit"
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
    window.hasAdminPermissionCachedSync = permission => {
        const token = sessionStorage.getItem("admin_token");
        const permissions = readCachedAdminPermissions(token) || [];
        return permissions.includes(permission);
    };
    window.checkAccess = cachedCheckAccess;

    function addAdminSidebarMenuItems() {
        const nav = document.querySelector("body > .sidebar .nav-links");
        if (!nav) return;
        const dashboardLink = Array.from(nav.querySelectorAll("a")).find(link =>
            String(link.getAttribute("href") || link.getAttribute("onclick") || "")
                .toLowerCase()
                .includes("/admin/dashboard")
        );
        if (dashboardLink?.closest("li")) {
            const dashboardItem = dashboardLink.closest("li");
            dashboardItem.dataset.permission = "Dashboard";
            getAdminPermissions(false).then(permissions => {
                dashboardItem.style.display = permissions.includes("Dashboard") ? "" : "none";
            }).catch(() => {
                dashboardItem.style.display = "none";
            });
        }
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

            getAdminPermissions(false).then(permissions => {
                item.style.display = permissions.includes(permission) ? "" : "none";
            }).catch(() => {
                item.style.display = "none";
            });

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
            "For-Disposal",
            "/static/photos/handw.png"
        );
        insertAfterLink(
            "/admin/reports",
            "adminAuditLogsNav",
            "Audit Logs",
            "/admin/Audit-Logs",
            "Audit-Logs",
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

    const ADMIN_ACTION_UI_RULES = {
        messages: [
            { permission: "Messages-Send", selectors: [
                '[onclick*="openNewMessagePage"]',
                '[onclick*="sendNewMessage"]',
                '[onclick*="sendReply"]'
            ] },
            { permission: "Messages-Manage", selectors: [
                '[onclick*="archiveMessage"]',
                '[onclick*="deleteMessage"]',
                '[onclick*="handleDeleteConversation"]'
            ] }
        ],
        lost: [
            { permission: "Lost-Reports-Create", selectors: [
                '.action-bar [onclick*="openModal(\'reportModal\')"]',
                '#reportModal [onclick*="submitReport"]',
                '#confirmModal [onclick*="executeSubmit"]'
            ] },
            { permission: "Claim-Management-Create", selectors: [
                '#possibleMatchesPanel button',
                '[onclick*="applySelectedPossibleMatch"]'
            ] },
            { permission: "Lost-Reports-Archive", selectors: [
                '[onclick*="runAdminBulkItemAction(\'lost\', \'archive\')"]',
                '#recoverBtn'
            ] },
            { permission: "Lost-Reports-Delete", selectors: [
                '[onclick*="runAdminBulkItemAction(\'lost\', \'delete\')"]',
                '#deleteBtn'
            ] }
        ],
        found: [
            { permission: "Found-Reports-Create", selectors: [
                '.action-bar [onclick*="openModal(\'reportModal\')"]',
                '#reportModal [onclick*="submitReport"]',
                '#confirmModal [onclick*="executeSubmit"]'
            ] },
            { permission: "Found-Reports-Approve", selectors: ['#approveBtn'] },
            { permission: "Found-Reports-Archive", selectors: ['#rejectBtn'] },
            { permission: "Claim-Management-Create", selectors: [
                '#manualClaimBtn',
                '#claimedBtn',
                '#confirmDirectClaimBtn'
            ] },
            { permission: "Found-Reports-Archive", selectors: [
                '[onclick*="runAdminBulkItemAction(\'found\', \'archive\')"]',
                '#recoverBtn'
            ] },
            { permission: "Found-Reports-Delete", selectors: [
                '[onclick*="runAdminBulkItemAction(\'found\', \'delete\')"]',
                '#deleteBtn'
            ] },
            { permission: "For-Disposal-Manage", selectors: [
                '[onclick*="runAdminBulkItemAction(\'found\', \'dispose\')"]',
                '#disposeBtn'
            ] }
        ],
        claims: [
            { permission: "Claim-Management-Decide", selectors: [
                '[onclick*="openDecisionModal"]',
                '[onclick*="saveDecisionReport"]'
            ] }
        ],
        reports: [
            { permission: "Reports-Export", selectors: [
                '[onclick*="generateReportPdf"]',
                '[onclick*="printClaimReport"]'
            ] },
            { permission: "Reports-Manage", selectors: [
                '.report-action.edit',
                '.report-action.delete',
                '#deleteSelectedButton',
                '[onclick*="saveClaimReport"]'
            ] },
            { permission: "Claim-Management-Decide", selectors: [
                '[onclick*="saveClaimReport"]'
            ] }
        ],
        confiscated: [
            { permission: "Confiscated-items-Create", selectors: [
                '[onclick*="openConfiscatedModal"]',
                '[onclick*="submitConfiscated"]',
                '[onclick*="openReasonManager"]',
                '[onclick*="addConfiscationReason"]',
                '[onclick*="saveConfiscationReason"]',
                '[onclick*="deleteConfiscationReason"]'
            ] },
            { permission: "Confiscated-items-Edit", selectors: ['[onclick*="editConfiscated"]'] },
            { permission: "Confiscated-items-Delete", selectors: ['[onclick*="deleteConfiscated"]'] },
            { permission: "For-Disposal-Manage", selectors: [
                '[onclick*="updateDisposal"]',
                '[onclick*="bulkDisposalAction"]'
            ] }
        ],
        disposal: [
            { permission: "For-Disposal-Manage", selectors: [
                '[onclick*="updateDisposal"]',
                '[onclick*="bulkDisposalAction"]'
            ] }
        ],
        content: [
            { permission: "Content-management-Announcements", selectors: [
                '[onclick*="openModal(\'announcementModal\')"]',
                '[onclick*="submitAnnouncement"]',
                '[onclick*="executeSubmitAnnouncement"]'
            ] },
            { permission: "Content-management-Taxonomy", selectors: [
                '[onclick*="createCategory"]',
                '[onclick*="createDepartment"]',
                '[onclick*="deleteCategory"]',
                '[onclick*="deleteDepartment"]'
            ] },
            { permission: "Content-management-Term", selectors: [
                '[onclick*="saveAcademicTermSchedule"]'
            ] },
            { permission: "Content-management-Edit", selectors: [
                '[onclick*="toggleEditMode"]',
                '[onclick*="saveDirectChanges"]',
                '[onclick*="saveAboutChanges"]',
                '[onclick*="saveExploreChanges"]'
            ] }
        ]
    };

    function getCurrentAdminActionModule() {
        const path = window.location.pathname.toLowerCase();
        const query = new URLSearchParams(window.location.search);
        const aliases = {
            "/c/073de3ca-5067-553d-90ba-9033ea9be665": "messages",
            "/c/6a12cb4b-be2c-83ec-ae4b-671169ad8496": "lost",
            "/c/f63b7f52-4bb0-5d24-8a09-80b3d1f77db2": "found",
            "/c/f97a07ee-7138-519e-8e81-c077ced9ee0a": "claims",
            "/c/8c2dc56e-79ae-5939-890e-315c8a959b32": query.get("view") === "audit" ? "audit" : "reports",
            "/c/dd5c6fcb-8cb9-54c8-bb07-d8b3f6e2aa79": query.get("view") === "disposal" ? "disposal" : "confiscated",
            "/c/9374b372-d94f-5fa4-a36d-e219bd12e3a6": "disposal",
            "/c/ab3bc951-819c-5bd7-aa04-2740b55a64a4": "content",
            "/c/cf6ffae9-1082-5e37-b051-3fffd2866f74": "content",
            "/c/cb34df2e-2169-53be-867e-37b9fd08a7e6": "content",
            "/c/d5e2c76e-2d33-5318-ba15-b150695800aa": "content"
        };
        if (aliases[path]) return aliases[path];
        if (path.includes("/messages")) return "messages";
        if (path.includes("/lost_items_report")) return "lost";
        if (path.includes("/found_items_report")) return "found";
        if (path.includes("/claim-management")) return "claims";
        if (path.includes("/audit-logs")) return "audit";
        if (path.includes("/for-disposal")) return "disposal";
        if (path.includes("/confiscated-items")) return query.get("view") === "disposal" ? "disposal" : "confiscated";
        if (path.includes("/reports")) return query.get("view") === "audit" ? "audit" : "reports";
        if (path.includes("/content-")) return "content";
        return "";
    }

    async function enforceAdminActionVisibility() {
        const moduleName = getCurrentAdminActionModule();
        const rules = ADMIN_ACTION_UI_RULES[moduleName] || [];
        if (!rules.length) return;

        let permissions = [];
        try {
            permissions = await getAdminPermissions(false);
        } catch (_) {
            permissions = [];
        }

        const applyRules = root => {
            rules.forEach(rule => {
                if (permissions.includes(rule.permission)) return;
                rule.selectors.forEach(selector => {
                    const matches = [];
                    if (root.matches?.(selector)) matches.push(root);
                    root.querySelectorAll?.(selector).forEach(element => matches.push(element));
                    matches.forEach(element => {
                        if (element.dataset.permissionHidden === rule.permission) return;
                        element.dataset.permissionHidden = rule.permission;
                        element.hidden = true;
                        element.setAttribute("aria-hidden", "true");
                        element.style.setProperty("display", "none", "important");
                    });
                });
            });
        };

        applyRules(document);
        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                if (mutation.type === "childList") {
                    mutation.addedNodes.forEach(node => {
                        if (node.nodeType === Node.ELEMENT_NODE) applyRules(node);
                    });
                } else if (mutation.target?.dataset?.permissionHidden) {
                    if (!mutation.target.hidden) mutation.target.hidden = true;
                    if (
                        mutation.target.style.display !== "none"
                        || mutation.target.style.getPropertyPriority("display") !== "important"
                    ) {
                        mutation.target.style.setProperty("display", "none", "important");
                    }
                }
            });
        });
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ["style", "hidden"]
        });
    }

    initializeSessionKeepAlive();
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", preloadAdminPermissions, { once: true });
        document.addEventListener("DOMContentLoaded", loadTopbarProfileAvatar, { once: true });
        document.addEventListener("DOMContentLoaded", addAdminSidebarMenuItems, { once: true });
        document.addEventListener("DOMContentLoaded", enforceAdminActionVisibility, { once: true });
    } else {
        preloadAdminPermissions();
        loadTopbarProfileAvatar();
        addAdminSidebarMenuItems();
        enforceAdminActionVisibility();
    }
})();
