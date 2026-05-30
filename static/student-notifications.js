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

    function getNotificationLabel(type) {
        if (type === "student_match") return "Possible Match";
        if (type === "chat") return "";
        return "Update";
    }

    function setHeaderIconLabels() {
        document.querySelectorAll(".message-icon").forEach((icon) => {
            icon.setAttribute("title", "Messages");
            icon.setAttribute("aria-label", "Messages");
        });

        document.querySelectorAll(".notification-bell").forEach((icon) => {
            icon.setAttribute("title", "Notifications");
            icon.setAttribute("aria-label", "Notifications");
        });

        document.querySelectorAll(".profile-trigger, .profile-icon").forEach((icon) => {
            icon.setAttribute("title", "Profile");
            icon.setAttribute("aria-label", "Profile");
        });
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
                ${getNotificationLabel(notif.type) ? `<strong>${getNotificationLabel(notif.type)}:</strong>` : ""}
                ${escapeHtml(notif.message)}
            </li>
        `).join("");

        countBadge.innerText = formatUnreadCount(unreadCount);
        countBadge.style.display = unreadCount > 0 ? "inline-flex" : "none";
    }

    async function updateMessageUnreadBadge() {
        const badge = document.getElementById("totalUnreadBadge");
        const token = getStudentToken();
        if (!badge || !token) return;

        try {
            const response = await fetch("/api/messages/unread-count", {
                headers: getStudentAuthHeader()
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Failed to load message unread count.");
            }

            const count = Number(data.unread_count || 0);
            badge.innerText = formatUnreadCount(count);
            badge.style.display = count > 0 ? "inline-flex" : "none";
        } catch (error) {
            console.error("Student message unread count load failed:", error);
        }
    }

    function getMessagePageUrl() {
        return "/student/Messages";
    }

    function formatMessageTime(value) {
        if (!value) return "";
        const normalized = String(value).replace(" ", "T");
        const date = new Date(normalized.endsWith("Z") || normalized.includes("+") ? normalized : `${normalized}+08:00`);
        if (Number.isNaN(date.getTime())) return "";
        return date.toLocaleString([], {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit"
        });
    }

    function ensureMessageDropdown() {
        const container = document.querySelector(".message-container");
        const trigger = document.querySelector(".message-icon");
        if (!container || !trigger) return;

        let dropdown = document.getElementById("messageDropdown");
        if (!dropdown) {
            dropdown = document.createElement("div");
            dropdown.id = "messageDropdown";
            dropdown.className = "message-dropdown notification-dropdown";
            dropdown.innerHTML = `
                <h3>Recent Messages</h3>
                <ul id="messageNotificationList"></ul>
                <div id="emptyMessageNotif" class="no-notif-msg">No message interactions yet</div>
            `;
            container.appendChild(dropdown);
        }

        trigger.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            toggleMessages();
        });
    }

    function renderMessageDropdown(interactions) {
        const list = document.getElementById("messageNotificationList");
        const empty = document.getElementById("emptyMessageNotif");
        if (!list || !empty) return;

        if (!interactions.length) {
            list.innerHTML = "";
            empty.style.display = "block";
            return;
        }

        empty.style.display = "none";
        list.innerHTML = interactions.map((item) => {
            const unread = Number(item.unread_count || 0);
            const previewPrefix = item.is_outgoing ? "You: " : "";
            const preview = `${previewPrefix}${item.last_message || ""}`.trim() || "New message";
            const badge = unread > 0 ? `<span class="message-count-pill">${formatUnreadCount(unread)}</span>` : "";
            return `
                <li class="message-notification-item ${unread > 0 ? "unread" : "read"}" data-partner-id="${item.partner_id}">
                    <div class="message-notification-main">
                        <div class="message-notification-title">
                            <strong>${escapeHtml(item.partner_name || item.partner_email || "User")}</strong>
                            ${badge}
                        </div>
                        <div class="message-notification-meta">${escapeHtml(item.role_label || "User")} &middot; ${formatMessageTime(item.last_message_at)}</div>
                        <div class="message-notification-preview">${escapeHtml(preview)}</div>
                    </div>
                </li>
            `;
        }).join("");

        list.querySelectorAll(".message-notification-item").forEach((item) => {
            item.addEventListener("click", () => openMessageInteraction(Number(item.dataset.partnerId)));
        });
    }

    async function loadMessageInteractions() {
        if (!getStudentToken()) return [];

        try {
            const response = await fetch("/api/messages/recent", {
                headers: getStudentAuthHeader()
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || "Failed to load recent messages.");
            }

            const interactions = Array.isArray(data) ? data : [];
            renderMessageDropdown(interactions);
            updateMessageUnreadBadge();
            return interactions;
        } catch (error) {
            console.error("Student message dropdown load failed:", error);
            return [];
        }
    }

    async function openMessageInteraction(partnerId) {
        if (!partnerId) return;

        try {
            await fetch(`/api/messages/read/${partnerId}`, {
                method: "POST",
                headers: getStudentAuthHeader()
            });
        } catch (error) {
            console.error("Student message read sync failed:", error);
        }

        const dropdown = document.getElementById("messageDropdown");
        if (dropdown) dropdown.style.display = "none";
        updateMessageUnreadBadge();

        if ((window.location.pathname || "").toLowerCase() === "/student/messages" && typeof window.openChat === "function") {
            const item = document.querySelector(`.message-notification-item[data-partner-id="${partnerId}"]`);
            const name = item?.querySelector(".message-notification-title strong")?.textContent || "User";
            window.openChat(partnerId, name);
            return;
        }

        window.location.href = getMessagePageUrl();
    }

    function closeMessageDropdown() {
        const dropdown = document.getElementById("messageDropdown");
        if (dropdown) dropdown.style.display = "none";
    }

    function toggleMessages() {
        const dropdown = document.getElementById("messageDropdown");
        if (!dropdown) return;

        const isOpen = dropdown.style.display === "block";
        document.querySelectorAll(".message-dropdown, .notification-dropdown, .profile-dropdown")
            .forEach((item) => {
                item.style.display = "none";
            });

        dropdown.style.display = isOpen ? "none" : "block";
        if (!isOpen) {
            loadMessageInteractions();
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
                Mark all as read
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
    window.setHeaderIconLabels = setHeaderIconLabels;
    window.updateMessageUnreadBadge = updateMessageUnreadBadge;
    window.toggleMessages = toggleMessages;
    window.loadMessageInteractions = loadMessageInteractions;

    document.addEventListener("DOMContentLoaded", () => {
        setHeaderIconLabels();
        ensureMessageDropdown();
        updateMessageUnreadBadge();
        loadMessageInteractions();
        setInterval(updateMessageUnreadBadge, 10000);
        if (document.getElementById("notificationList")) {
            ensureNotificationActions();
            loadNotifications();
            setInterval(loadNotifications, 30000);
        }
    });

    document.addEventListener("click", (event) => {
        if (!event.target.closest(".message-container")) {
            closeMessageDropdown();
        }
    });
})();
