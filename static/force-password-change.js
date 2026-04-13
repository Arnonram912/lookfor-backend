(function () {
    function decodeTokenPayload(token) {
        try {
            return JSON.parse(atob(token.split(".")[1]));
        } catch (error) {
            return null;
        }
    }

    function getStoredToken() {
        const currentPath = (window.location.pathname || "").toLowerCase();
        const adminToken = localStorage.getItem("admin_token");
        const studentToken = localStorage.getItem("token");

        if (currentPath.startsWith("/admin")) {
            return adminToken;
        }

        if (currentPath.startsWith("/student")) {
            if (studentToken) return studentToken;

            const fallbackPayload = decodeTokenPayload(adminToken || "");
            return fallbackPayload && !fallbackPayload.is_admin ? adminToken : null;
        }

        return adminToken || studentToken;
    }

    function ensureModal() {
        let overlay = document.getElementById("mustChangeModal");
        if (overlay) return overlay;

        overlay = document.createElement("div");
        overlay.id = "mustChangeModal";
        overlay.style.cssText = [
            "display:none",
            "position:fixed",
            "inset:0",
            "background:rgba(0,0,0,.65)",
            "z-index:10000",
            "justify-content:center",
            "align-items:center",
            "padding:20px"
        ].join(";");

        overlay.innerHTML = `
            <div style="width:min(420px,100%); background:#fff; border-radius:18px; padding:26px 24px; box-shadow:0 24px 50px rgba(0,0,0,.22); font-family:Montserrat,sans-serif;">
                <h2 style="color:#003366; margin:0 0 10px;">Secure Your Account</h2>
                <p style="color:#555; margin:0 0 20px;">Please set a new password to continue.</p>

                <form id="forceChangeForm">
                    <div style="text-align:left;">
                        <label for="newPass" style="display:block; font-size:12px; font-weight:700; margin-bottom:8px;">NEW PASSWORD</label>
                        <input type="password" id="newPass" placeholder="Enter new password" required
                               style="width:100%; padding:12px 14px; border:1px solid #d8dee8; border-radius:12px; font-size:14px; box-sizing:border-box;">
                        <div id="password-requirements" style="text-align:left; font-size:12px; margin-top:10px; color:#666;">
                            <div id="req-length">× Min 8 characters</div>
                            <div id="req-upper">× One uppercase letter</div>
                            <div id="req-number">× One number</div>
                            <div id="req-special">× One special character (@$!%*?&)</div>
                        </div>
                    </div>

                    <div style="text-align:left; margin-top:16px;">
                        <label for="confirmPass" style="display:block; font-size:12px; font-weight:700; margin-bottom:8px;">CONFIRM PASSWORD</label>
                        <input type="password" id="confirmPass" placeholder="Repeat new password" required
                               style="width:100%; padding:12px 14px; border:1px solid #d8dee8; border-radius:12px; font-size:14px; box-sizing:border-box;">
                        <div id="match-message" style="font-size:12px; margin-top:6px;"></div>
                    </div>

                    <button type="submit"
                            style="margin-top:20px; width:100%; border:none; border-radius:12px; background:#0d6efd; color:#fff; font-weight:700; padding:12px 14px; cursor:pointer;">
                        Update & Continue
                    </button>
                </form>
            </div>
        `;

        document.body.appendChild(overlay);
        return overlay;
    }

    function updateRequirement(id, isMet) {
        const el = document.getElementById(id);
        if (!el) return;
        const currentText = el.textContent || "";
        el.style.color = isMet ? "green" : "#666";
        el.textContent = isMet ? currentText.replace("×", "✓") : currentText.replace("✓", "×");
    }

    function checkMatch() {
        const newPassInput = document.getElementById("newPass");
        const confirmPassInput = document.getElementById("confirmPass");
        const matchMsg = document.getElementById("match-message");
        if (!newPassInput || !confirmPassInput || !matchMsg) return;

        if (confirmPassInput.value === newPassInput.value && newPassInput.value !== "") {
            matchMsg.textContent = "✓ Passwords match";
            matchMsg.style.color = "green";
        } else {
            matchMsg.textContent = "× Passwords do not match";
            matchMsg.style.color = "red";
        }
    }

    function fallbackLogout() {
        localStorage.clear();
        document.cookie = "admin_access_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
        window.location.replace("/login");
    }

    function openForcedPasswordModal() {
        const overlay = ensureModal();
        const form = document.getElementById("forceChangeForm");
        const newPassInput = document.getElementById("newPass");
        const confirmPassInput = document.getElementById("confirmPass");

        if (!overlay || !form || !newPassInput || !confirmPassInput) return;

        overlay.style.display = "flex";
        document.body.style.overflow = "hidden";

        if (!form.dataset.bound) {
            newPassInput.addEventListener("input", () => {
                const val = newPassInput.value;
                updateRequirement("req-length", val.length >= 8);
                updateRequirement("req-upper", /[A-Z]/.test(val));
                updateRequirement("req-number", /[0-9]/.test(val));
                updateRequirement("req-special", /[@$!%*?&]/.test(val));
                checkMatch();
            });

            confirmPassInput.addEventListener("input", checkMatch);

            form.addEventListener("submit", async (event) => {
                event.preventDefault();
                const token = getStoredToken();
                const newPass = newPassInput.value;
                const confirmPass = confirmPassInput.value;
                const passwordRegex = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/;

                if (!passwordRegex.test(newPass)) {
                    alert("Password must be 8+ characters with uppercase, number, and special character.");
                    return;
                }

                if (newPass !== confirmPass) {
                    alert("Passwords do not match!");
                    return;
                }

                try {
                    const response = await fetch("/auth/change-password", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "Authorization": `Bearer ${token}`
                        },
                        body: JSON.stringify({ new_password: newPass })
                    });

                    if (response.ok) {
                        alert("Success! Please log in again.");
                        if (typeof window.logout === "function") {
                            window.logout();
                        } else {
                            fallbackLogout();
                        }
                    } else {
                        const errorData = await response.json();
                        alert(errorData.detail || "Failed to update password.");
                    }
                } catch (error) {
                    alert("Network error. Please try again.");
                }
            });

            form.dataset.bound = "true";
        }

        setTimeout(() => newPassInput.focus(), 0);
    }

    function initForcedPasswordFlow() {
        const token = getStoredToken();
        if (!token) return;

        const payload = decodeTokenPayload(token);
        if (!payload || !payload.must_change) return;

        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", openForcedPasswordModal, { once: true });
        } else {
            openForcedPasswordModal();
        }
    }

    initForcedPasswordFlow();
})();
