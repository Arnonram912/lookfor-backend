(function () {
    let notifications = [];

    function decodeTokenPayload(token) {
        try {
            return JSON.parse(atob(token.split(".")[1]));
        } catch (error) {
            return null;
        }
    }

    function getStudentToken() {
        const studentToken = localStorage.getItem("token");
        if (studentToken) return studentToken;

        const fallbackToken = localStorage.getItem("admin_token");
        const payload = decodeTokenPayload(fallbackToken || "");
        return payload && !payload.is_admin ? fallbackToken : null;
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

    async function loadNotifications() {
        const list = document.getElementById("notificationList");
        const countBadge = document.getElementById("notificationCount");
        const emptyState = document.getElementById("emptyNotif");
        const token = getStudentToken();

        if (!list || !countBadge || !emptyState || !token) return;

        try {
            const response = await fetch("/student/notifications", {
                headers: getStudentAuthHeader()
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Failed to load notifications.");
            }

            notifications = Array.isArray(data) ? data : [];

            if (!notifications.length) {
                list.innerHTML = "";
                emptyState.style.display = "block";
                countBadge.style.display = "none";
                countBadge.innerText = "0";
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

            const unreadCount = notifications.filter(notif => !notif.is_read).length;
            countBadge.innerText = unreadCount;
            countBadge.style.display = unreadCount > 0 ? "inline-flex" : "none";
        } catch (error) {
            console.error("Student notification load failed:", error);
        }
    }

    async function markStudentNotificationRead(notifId) {
        const notif = notifications.find((entry) => entry.id === notifId);

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

    window.loadNotifications = loadNotifications;
    window.markStudentNotificationRead = markStudentNotificationRead;

    document.addEventListener("DOMContentLoaded", () => {
        if (document.getElementById("notificationList")) {
            loadNotifications();
            setInterval(loadNotifications, 30000);
        }
    });
})();
