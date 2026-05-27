(function () {
    let notifications = [];
    let unreadCount = 0;

    function formatUnreadCount(count) {
        return count > 99 ? "99+" : String(count);
    }

    function decodeTokenPayload(token) {
        try {
            return JSON.parse(atob(token.split(".")[1]));
        } catch (error) {
            return null;
        }
    }

    function getStudentToken() {
        return localStorage.getItem("token");
    }

    function getStudentAuthHeader() {
        const token = getStudentToken();
        return token ? { Authorization: `Bearer ${token}` } : {};
    }

    function escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text || "";
        return div.innerHTML;
    }

    function updateNotificationUI() {
        const list = document.getElementById("notificationList");
        const countBadge = document.getElementById("notificationCount");
        const emptyState = document.getElementById("emptyNotif");

        if (!list || !countBadge || !emptyState) return;

        if (!notifications.length) {
            list.innerHTML = "";
            emptyState.style.display = "block";
            countBadge.style.display = unreadCount > 0 ? "inline-flex" : "none";
            countBadge.innerText = formatUnreadCount(unreadCount);
            return;
        }

        emptyState.style.display = "none";
        list.innerHTML = notifications.map(notif => `
            <li class="notification-item ${notif.is_read ? 'read' : 'unread'}"
                onclick="markStudentNotificationRead(${notif.id})"
                style="cursor:pointer;">
                <strong>${notif.type === 'student_match' ? 'Possible Match' : notif.type === 'chat' ? 'Message' : 'Update'}:</strong>
                ${escapeHtml(notif.message)}
            </li>
        `).join("");

        countBadge.innerText = formatUnreadCount(unreadCount);
        countBadge.style.display = unreadCount > 0 ? "inline-flex" : "none";
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
                await markAllStudentNotificationsRead();
            });
        }
    }

    async function loadUnreadCount() {
        const token = getStudentToken();
        if (!token) return 0;

        try {
            const response = await fetch("/student/notifications/unread-count", {
                headers: getStudentAuthHeader()
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Failed to load unread count.");
            }

            unreadCount = Number(data.unread_count || 0);
            updateNotificationUI();
            return unreadCount;
        } catch (error) {
            console.error("Student unread count load failed:", error);
            return unreadCount;
        }
    }

    async function loadNotifications() {
        const list = document.getElementById("notificationList");
        const countBadge = document.getElementById("notificationCount");
        const emptyState = document.getElementById("emptyNotif");
        const token = getStudentToken();

        if (!list || !countBadge || !emptyState || !token) return;

        try {
            const [response, unread] = await Promise.all([
                fetch("/student/notifications", {
                    headers: getStudentAuthHeader()
                }),
                loadUnreadCount()
            ]);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Failed to load notifications.");
            }

            notifications = Array.isArray(data) ? data : [];
            unreadCount = Number(unread || 0);
            updateNotificationUI();
        } catch (error) {
            console.error("Student notification load failed:", error);
        }
    }

    async function markStudentNotificationRead(notifId) {
        const notif = notifications.find((entry) => entry.id === notifId);
        if (notif && !notif.is_read) {
            notif.is_read = true;
            unreadCount = Math.max(0, unreadCount - 1);
            updateNotificationUI();
        }

        try {
            await fetch(`/student/notifications/${notifId}/read`, {
                method: "POST",
                headers: getStudentAuthHeader()
            });

            if (notif && notif.target_url) {
                window.location.href = notif.target_url;
                return;
            }

            if (notif && notif.type === "chat") {
                window.location.href = "/student/Messages";
                return;
            }

            if (notif && (notif.type === "student_match" || notif.type === "student_update")) {
                window.location.href = "/student/Lost-report";
                return;
            }

            loadNotifications();
        } catch (error) {
            console.error("Student notification read failed:", error);
        }
    }

    async function markAllStudentNotificationsRead() {
        if (!notifications.length || unreadCount <= 0) return;

        notifications = notifications.map((notif) => ({ ...notif, is_read: true }));
        unreadCount = 0;
        updateNotificationUI();

        try {
            await fetch("/student/notifications/mark-all-read", {
                method: "POST",
                headers: getStudentAuthHeader()
            });
        } catch (error) {
            console.error("Student mark-all-read sync failed:", error);
            loadNotifications();
        }
    }

    window.loadNotifications = loadNotifications;
    window.loadStudentNotificationUnreadCount = loadUnreadCount;
    window.markStudentNotificationRead = markStudentNotificationRead;
    window.markAllStudentNotificationsRead = markAllStudentNotificationsRead;

    document.addEventListener("DOMContentLoaded", () => {
        if (document.getElementById("notificationList")) {
            ensureNotificationActions();
            loadNotifications();
            setInterval(loadNotifications, 30000);
        }
    });
})();
