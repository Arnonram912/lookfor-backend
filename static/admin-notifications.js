(function () {
    const ADMIN_NOTIFICATION_POLL_MS = 30000;
    let notifications = [];
    let unreadCount = 0;
    let pollHandle = null;

    function getAdminToken() {
        return sessionStorage.getItem("admin_token");
    }

    function getAdminAuthHeader() {
        const token = getAdminToken();
        return token ? { Authorization: `Bearer ${token}` } : {};
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text || "";
        return div.innerHTML;
    }

    function syncGlobalNotifications() {
        window.notifications = notifications;
    }

    function getNotificationLabel(type) {
        if (type === "match") return "Possible Match";
        if (type === "chat") return "Message";
        if (type === "user_management_admin" || type === "user_management_students") return "User Update";
        return "Update";
    }

    function formatUnreadCount(count) {
        return count > 99 ? "99+" : String(count);
    }

    function updateNotificationUI() {
        const list = document.getElementById("notificationList");
        const countBadge = document.getElementById("notificationCount");
        const emptyMsg = document.getElementById("emptyNotif");

        if (!list) return;

        syncGlobalNotifications();
        list.innerHTML = "";

        if (!notifications.length) {
            if (emptyMsg) emptyMsg.style.display = "block";
            if (countBadge) {
                countBadge.innerText = formatUnreadCount(unreadCount);
                countBadge.style.display = unreadCount > 0 ? "inline-flex" : "none";
            }
            return;
        }

        if (emptyMsg) emptyMsg.style.display = "none";

        notifications.forEach((notif) => {
            const li = document.createElement("li");
            li.className = `notification-item ${notif.is_read ? "read" : "unread"}`;
            li.setAttribute("onclick", `handleNotifClick(${notif.id})`);
            li.style.cursor = "pointer";
            li.innerHTML = `
                <strong>${getNotificationLabel(notif.type)}:</strong>
                ${escapeHtml(notif.message)}
            `;
            list.appendChild(li);
        });

        if (countBadge) {
            countBadge.innerText = formatUnreadCount(unreadCount);
            countBadge.style.display = unreadCount > 0 ? "inline-flex" : "none";
        }
    }

    function ensureNotificationActions() {
        const dropdown = document.getElementById("notificationDropdown");
        const list = document.getElementById("notificationList");
        if (!dropdown || !list) return;

        let actions = document.getElementById("notificationActions");
        if (actions) return;

        actions = document.createElement("div");
        actions.id = "notificationActions";
        actions.className = "notification-actions";
        actions.innerHTML = `
            <button type="button" id="markAllNotificationsReadBtn" class="notification-action-btn">
                Read all unread
            </button>
        `;

        list.parentNode.insertBefore(actions, list);

        const button = document.getElementById("markAllNotificationsReadBtn");
        if (button) {
            button.addEventListener("click", async (event) => {
                event.preventDefault();
                event.stopPropagation();
                await markAllNotificationsRead();
            });
        }
    }

    async function loadUnreadCount() {
        const token = getAdminToken();
        if (!token) return 0;

        try {
            const response = await fetch("/admin/notifications/unread-count", {
                headers: getAdminAuthHeader()
            });

            if (!response.ok) {
                throw new Error("Failed to fetch admin unread count.");
            }

            const data = await response.json();
            unreadCount = Number(data.unread_count || 0);
            updateNotificationUI();
            return unreadCount;
        } catch (error) {
            console.error("Admin unread count sync failed:", error);
            return unreadCount;
        }
    }

    async function loadNotifications() {
        const token = getAdminToken();
        if (!token) return [];

        try {
            const [response, unread] = await Promise.all([
                fetch("/admin/notifications", {
                    headers: getAdminAuthHeader()
                }),
                loadUnreadCount()
            ]);

            if (!response.ok) {
                throw new Error("Failed to fetch admin notifications.");
            }

            const data = await response.json();
            notifications = Array.isArray(data) ? data : [];
            unreadCount = Number(unread || 0);
            updateNotificationUI();
            return notifications;
        } catch (error) {
            console.error("Admin notification sync failed:", error);
            return [];
        }
    }

    function closeNotificationDropdown() {
        const dropdown = document.getElementById("notificationDropdown");
        if (dropdown) {
            dropdown.style.display = "none";
        }
    }

    function routeNotification(notif) {
        if (notif && notif.target_url) {
            window.location.href = notif.target_url;
            return;
        }

        const currentPath = (window.location.pathname || "").toLowerCase();
        const message = String(notif.message || "").toLowerCase();

        if (notif.type === "user_management_students") {
            window.location.href = "/admin/User-Management?tab=student";
            return;
        }

        if (notif.type === "user_management_admin") {
            window.location.href = "/admin/User-Management?tab=admin";
            return;
        }

        if (notif.type === "chat" || message.includes("message")) {
            window.location.href = "/admin/Messages";
            return;
        }

        if (message.includes("claim")) {
            window.location.href = "/admin/Claim-Management";
            return;
        }

        if (notif.type === "match" || message.includes("found")) {
            if (currentPath === "/admin/dashboard" && typeof window.openFoundItemsModal === "function") {
                window.openFoundItemsModal();
                return;
            }

            window.location.href = "/admin/Found_Items_Report";
            return;
        }

        if (notif.type === "new_report" || message.includes("pending") || message.includes("surrender") || message.includes("reported")) {
            if (currentPath === "/admin/dashboard" && typeof window.openPendingSurrenderModal === "function") {
                window.openPendingSurrenderModal();
                return;
            }

            window.location.href = "/admin/Found_Items_Report";
        }
    }

    async function handleNotifClick(notifId) {
        const notif = notifications.find((entry) => entry.id === notifId);
        if (!notif) return;

        notif.is_read = true;
        unreadCount = Math.max(0, unreadCount - 1);
        updateNotificationUI();

        try {
            await fetch(`/admin/notifications/${notifId}/read`, {
                method: "POST",
                headers: getAdminAuthHeader()
            });
        } catch (error) {
            console.error("Admin notification read sync failed:", error);
        }

        if (typeof window.closeAllDropdowns === "function") {
            window.closeAllDropdowns();
        } else {
            closeNotificationDropdown();
        }

        routeNotification(notif);
    }

    async function markAllNotificationsRead() {
        if (!notifications.length || unreadCount <= 0) return;

        notifications = notifications.map((notif) => ({ ...notif, is_read: true }));
        unreadCount = 0;
        updateNotificationUI();

        try {
            await fetch("/admin/notifications/mark-all-read", {
                method: "POST",
                headers: getAdminAuthHeader()
            });
        } catch (error) {
            console.error("Admin mark-all-read sync failed:", error);
            loadNotifications();
        }
    }

    function toggleNotifications() {
        const dropdown = document.getElementById("notificationDropdown");
        if (!dropdown) return;

        const isOpen = dropdown.style.display === "block";
        if (typeof window.closeAllDropdowns === "function") {
            window.closeAllDropdowns();
        } else {
            closeNotificationDropdown();
        }

        dropdown.style.display = isOpen ? "none" : "block";
        if (!isOpen) {
            loadNotifications();
        }
    }

    function initAdminNotifications() {
        if (pollHandle || !document.getElementById("notificationList")) return;

        ensureNotificationActions();
        loadNotifications();
        pollHandle = window.setInterval(loadNotifications, ADMIN_NOTIFICATION_POLL_MS);
    }

    window.loadNotifications = loadNotifications;
    window.loadAdminNotificationUnreadCount = loadUnreadCount;
    window.updateNotificationUI = updateNotificationUI;
    window.handleNotifClick = handleNotifClick;
    window.markAllNotificationsRead = markAllNotificationsRead;
    window.toggleNotifications = toggleNotifications;
    window.initAdminNotifications = initAdminNotifications;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAdminNotifications);
    } else {
        initAdminNotifications();
    }
})();
