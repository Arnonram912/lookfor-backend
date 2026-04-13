(function () {
    const ADMIN_NOTIFICATION_POLL_MS = 30000;
    let notifications = [];
    let pollHandle = null;

    function getAdminToken() {
        return localStorage.getItem("admin_token");
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
                countBadge.innerText = "0";
                countBadge.style.display = "none";
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

        const unreadCount = notifications.filter((notif) => !notif.is_read).length;
        if (countBadge) {
            countBadge.innerText = String(unreadCount);
            countBadge.style.display = unreadCount > 0 ? "inline-flex" : "none";
        }
    }

    async function loadNotifications() {
        const token = getAdminToken();
        if (!token) return [];

        try {
            const response = await fetch("/admin/notifications", {
                headers: getAdminAuthHeader()
            });

            if (!response.ok) {
                throw new Error("Failed to fetch admin notifications.");
            }

            const data = await response.json();
            notifications = Array.isArray(data) ? data : [];
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

        loadNotifications();
        pollHandle = window.setInterval(loadNotifications, ADMIN_NOTIFICATION_POLL_MS);
    }

    window.loadNotifications = loadNotifications;
    window.updateNotificationUI = updateNotificationUI;
    window.handleNotifClick = handleNotifClick;
    window.toggleNotifications = toggleNotifications;
    window.initAdminNotifications = initAdminNotifications;
})();
