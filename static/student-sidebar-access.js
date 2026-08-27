(function () {
    const ALLOWED_WHEN_DEACTIVATED = new Set([
        "/student/profile",
        "/student/settings",
        "/faculty/profile",
        "/faculty/settings"
    ]);

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

    function normalizePath(path) {
        return (path || "").replace(/\/+$/, "").toLowerCase();
    }

    function rewriteFacultyPageLinks() {
        document.querySelectorAll('a[href^="/student/"]').forEach((link) => {
            link.setAttribute("href", link.getAttribute("href").replace("/student/", "/faculty/"));
        });
        document.querySelectorAll('[onclick*="/student/"]').forEach((element) => {
            element.setAttribute("onclick", element.getAttribute("onclick").replaceAll("/student/", "/faculty/"));
        });
    }

    function showNoAccessPopup(accountLabel = "Student") {
        const existing = document.getElementById("student-no-access-modal");
        if (existing) {
            existing.style.display = "flex";
            return;
        }

        const overlay = document.createElement("div");
        overlay.id = "student-no-access-modal";
        overlay.style = `
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0, 0, 0, 0.7); display: flex;
            justify-content: center; align-items: center; z-index: 9999;
            backdrop-filter: blur(4px);
        `;

        overlay.innerHTML = `
            <div style="background: white; padding: 36px; border-radius: 14px; text-align: center; max-width: 420px; box-shadow: 0 10px 25px rgba(0,0,0,0.35);">
                <div style="font-size: 48px; margin-bottom: 16px;">🔒</div>
                <h2 style="color: #d9534f; margin-bottom: 10px; font-family: 'Montserrat', sans-serif;">No Access</h2>
                <p style="color: #555; line-height: 1.5;">
                    Your ${accountLabel.toLowerCase()} account is currently deactivated. Please wait for admin activation before opening this page.
                </p>
                <button onclick="document.getElementById('student-no-access-modal').remove()"
                    style="margin-top: 22px; padding: 12px 28px; background: #003366; color: white; border: none; border-radius: 8px; cursor: pointer; font-weight: 600;">
                    Close
                </button>
            </div>
        `;

        document.body.appendChild(overlay);
    }

    async function initStudentSidebarAccess() {
        const token = getStudentToken();
        if (!token) return;

        try {
            const response = await fetch("/api/current-user", {
                headers: { "Authorization": `Bearer ${token}` }
            });

            if (!response.ok) return;

            const currentUser = await response.json();
            if (currentUser.is_admin) {
                window.location.replace("/admin/dashboard");
                return;
            }

            const roleLabel = String(currentUser.role_label || "Student");
            if (["Faculty", "Staff"].includes(roleLabel)) {
                document.title = `${roleLabel} Portal | LookFor STI`;
            }
            const isFaculty = roleLabel === "Faculty";
            document.body.dataset.portalRole = roleLabel.toLowerCase();
            window.lookforPortalRoot = isFaculty ? "/faculty" : "/student";
            if (isFaculty) rewriteFacultyPageLinks();

            const sidebarLinks = Array.from(document.querySelectorAll('.sidebar .nav-links a[href^="/student/"], .sidebar .nav-links a[href^="/faculty/"]'));
            if (sidebarLinks.length === 0) return;

            if (currentUser.is_student_active) return;

            sidebarLinks.forEach((link) => {
                const targetPath = normalizePath(link.getAttribute("href"));
                if (ALLOWED_WHEN_DEACTIVATED.has(targetPath)) return;

                link.addEventListener("click", (event) => {
                    event.preventDefault();
                    showNoAccessPopup(roleLabel);
                });
            });
        } catch (error) {
            console.error("Student sidebar access guard failed:", error);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initStudentSidebarAccess, { once: true });
    } else {
        initStudentSidebarAccess();
    }
})();
