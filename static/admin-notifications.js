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
        if (type === "chat") return "";
        if (type === "user_management_admin" || type === "user_management_students") return "User Update";
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
            const label = getNotificationLabel(notif.type);
            li.innerHTML = `
                ${label ? `<strong>${label}:</strong>` : ""}
                ${escapeHtml(notif.message)}
            `;
            list.appendChild(li);
        });

        if (countBadge) {
            countBadge.innerText = formatUnreadCount(unreadCount);
            countBadge.style.display = unreadCount > 0 ? "inline-flex" : "none";
        }
    }

    async function updateMessageUnreadBadge() {
        const badge = document.getElementById("totalUnreadBadge");
        const token = getAdminToken();
        if (!badge || !token) return;

        try {
            const response = await fetch("/admin/api/messages/unread-count", {
                headers: getAdminAuthHeader()
            });

            if (!response.ok) {
                throw new Error("Failed to fetch admin message unread count.");
            }

            const data = await response.json();
            const count = Number(data.unread_count || 0);
            badge.innerText = formatUnreadCount(count);
            badge.style.display = count > 0 ? "inline-flex" : "none";
        } catch (error) {
            console.error("Admin message unread count sync failed:", error);
        }
    }

    function getMessagePageUrl() {
        return "/admin/Messages";
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
        if (!getAdminToken()) return [];

        try {
            const response = await fetch("/api/messages/recent", {
                headers: getAdminAuthHeader()
            });

            if (!response.ok) {
                throw new Error("Failed to fetch recent messages.");
            }

            const interactions = await response.json();
            renderMessageDropdown(Array.isArray(interactions) ? interactions : []);
            updateMessageUnreadBadge();
            return interactions;
        } catch (error) {
            console.error("Admin message dropdown sync failed:", error);
            return [];
        }
    }

    async function openMessageInteraction(partnerId) {
        if (!partnerId) return;

        try {
            await fetch(`/api/messages/read/${partnerId}`, {
                method: "POST",
                headers: getAdminAuthHeader()
            });
        } catch (error) {
            console.error("Admin message read sync failed:", error);
        }

        const dropdown = document.getElementById("messageDropdown");
        if (dropdown) dropdown.style.display = "none";
        updateMessageUnreadBadge();

        if ((window.location.pathname || "").toLowerCase() === "/admin/messages" && typeof window.openChat === "function") {
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

        setHeaderIconLabels();
        ensureMessageDropdown();
        ensureNotificationActions();
        updateMessageUnreadBadge();
        loadMessageInteractions();
        loadNotifications();
        pollHandle = window.setInterval(loadNotifications, ADMIN_NOTIFICATION_POLL_MS);
        window.setInterval(updateMessageUnreadBadge, 10000);
    }

    window.loadNotifications = loadNotifications;
    window.loadAdminNotificationUnreadCount = loadUnreadCount;
    window.updateNotificationUI = updateNotificationUI;
    window.handleNotifClick = handleNotifClick;
    window.markAllNotificationsRead = markAllNotificationsRead;
    window.toggleNotifications = toggleNotifications;
    window.toggleMessages = toggleMessages;
    window.loadMessageInteractions = loadMessageInteractions;
    window.initAdminNotifications = initAdminNotifications;
    window.setHeaderIconLabels = setHeaderIconLabels;
    window.updateMessageUnreadBadge = updateMessageUnreadBadge;

    document.addEventListener("click", (event) => {
        if (!event.target.closest(".message-container")) {
            closeMessageDropdown();
        }
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAdminNotifications);
    } else {
        initAdminNotifications();
    }
})();
