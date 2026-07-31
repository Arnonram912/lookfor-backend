(function () {
    "use strict";

    const script = document.currentScript;
    const pageItemType = script?.dataset?.itemType || "item";
    const reloadFunctionName = script?.dataset?.reload || "";
    let activeItem = null;
    let activeRecordType = pageItemType;
    let categories = [];

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function authToken() {
        return sessionStorage.getItem("admin_token") || localStorage.getItem("token") || "";
    }

    function recordTypeFor(item) {
        return item?.status === "pending_found" || item?.is_pending ? "pending-found" : pageItemType;
    }

    function isPendingEditable(item, recordType) {
        if (!item || item.archived || item.deleted) return false;
        if (recordType === "pending-found") return true;
        return String(item.status || "").toLowerCase() === "lost"
            && !item.is_matched
            && !item.is_claimed;
    }

    function installMarkup() {
        if (document.getElementById("itemDetailEditModal")) return;

        const style = document.createElement("style");
        style.textContent = `
            .item-detail-edit-btn{border:0;border-radius:9px;padding:10px 16px;background:#0b63a5;color:#fff;font-weight:700;cursor:pointer}
            .item-detail-edit-btn:hover{background:#084d82}
            #itemDetailEditModal{z-index:1200}
            #itemDetailEditModal .item-edit-card{width:min(92vw,720px);max-height:90vh;overflow:auto;padding:28px}
            .item-edit-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
            .item-edit-field{display:flex;flex-direction:column;gap:6px}
            .item-edit-field.full{grid-column:1/-1}
            .item-edit-field label{font-weight:700;color:#17324d}
            .item-edit-field input,.item-edit-field select,.item-edit-field textarea{width:100%;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:9px;padding:10px 12px;font:inherit}
            .item-edit-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}
            .item-edit-cancel{border:1px solid #94a3b8;border-radius:9px;padding:10px 16px;background:#fff;cursor:pointer}
            #itemEditAnalysis{margin-top:18px;padding:14px;border-radius:10px;background:#f2f7fc;color:#17324d}
            .item-edit-match{margin-top:8px;padding:9px 10px;background:#fff;border:1px solid #d8e4ef;border-radius:8px}
            @media(max-width:640px){.item-edit-grid{grid-template-columns:1fr}.item-edit-field.full{grid-column:auto}}
        `;
        document.head.appendChild(style);

        const modal = document.createElement("div");
        modal.id = "itemDetailEditModal";
        modal.className = "modal-overlay";
        modal.style.display = "none";
        modal.innerHTML = `
            <div class="modal-content item-edit-card" role="dialog" aria-modal="true" aria-labelledby="itemEditTitle">
                <span class="close-btn" data-item-edit-close>&times;</span>
                <h2 id="itemEditTitle" style="margin:0 0 18px;color:#0b3d68">Edit Pending Item Details</h2>
                <form id="itemDetailEditForm">
                    <div class="item-edit-grid">
                        <div class="item-edit-field full"><label for="itemEditName">Item name *</label><input id="itemEditName" maxlength="255" required></div>
                        <div class="item-edit-field"><label for="itemEditCategory">Category *</label><select id="itemEditCategory" required><option value="">Loading categories...</option></select></div>
                        <div class="item-edit-field"><label for="itemEditDate">Date *</label><input id="itemEditDate" type="date" required></div>
                        <div class="item-edit-field"><label for="itemEditBrand">Brand</label><input id="itemEditBrand" maxlength="100"></div>
                        <div class="item-edit-field"><label for="itemEditColor">Color</label><input id="itemEditColor" maxlength="50"></div>
                        <div class="item-edit-field full"><label for="itemEditLocation">Location *</label><input id="itemEditLocation" maxlength="500" required></div>
                        <div class="item-edit-field"><label for="itemEditTime">Time</label><input id="itemEditTime" type="time"></div>
                        <div class="item-edit-field full"><label for="itemEditDescription">Description</label><textarea id="itemEditDescription" maxlength="4000" rows="4"></textarea></div>
                    </div>
                    <div id="itemEditAnalysis" style="display:none"></div>
                    <div class="item-edit-actions">
                        <button type="button" class="item-edit-cancel" data-item-edit-close>Cancel</button>
                        <button type="submit" id="itemEditSaveBtn" class="item-detail-edit-btn">Save & Analyze Match</button>
                    </div>
                </form>
            </div>
        `;
        document.body.appendChild(modal);
        modal.querySelectorAll("[data-item-edit-close]").forEach((button) => {
            button.addEventListener("click", closeEditor);
        });
        modal.addEventListener("click", (event) => {
            if (event.target === modal) closeEditor();
        });
        document.getElementById("itemDetailEditForm").addEventListener("submit", saveDetails);
    }

    async function loadCategories() {
        if (categories.length) return categories;
        const response = await fetch("/api/categories");
        if (!response.ok) throw new Error("Could not load item categories.");
        categories = await response.json();
        return categories;
    }

    function closeEditor() {
        document.getElementById("itemDetailEditModal").style.display = "none";
    }

    async function openEditor() {
        if (!activeItem) return;
        installMarkup();
        const modal = document.getElementById("itemDetailEditModal");
        const analysis = document.getElementById("itemEditAnalysis");
        const saveButton = document.getElementById("itemEditSaveBtn");
        saveButton.disabled = false;
        saveButton.textContent = "Save & Analyze Match";
        analysis.style.display = "none";
        analysis.innerHTML = "";

        try {
            await loadCategories();
        } catch (error) {
            analysis.style.display = "block";
            analysis.textContent = error.message;
        }

        const select = document.getElementById("itemEditCategory");
        select.innerHTML = '<option value="">-- Select Category --</option>' + categories.map((category) =>
            `<option value="${Number(category.id)}">${escapeHtml(category.name)}</option>`
        ).join("");
        const matchingCategory = categories.find((category) =>
            Number(category.id) === Number(activeItem.category_id) ||
            String(category.name).toLowerCase() === String(activeItem.category || "").toLowerCase()
        );

        document.getElementById("itemEditName").value = activeItem.item_name || "";
        select.value = matchingCategory ? String(matchingCategory.id) : "";
        document.getElementById("itemEditBrand").value = activeItem.brand || "";
        document.getElementById("itemEditColor").value = activeItem.color || "";
        document.getElementById("itemEditLocation").value = activeItem.location || "";
        document.getElementById("itemEditDate").value = String(activeItem.date || "").slice(0, 10);
        document.getElementById("itemEditTime").value = String(activeItem.time_found || "").slice(0, 5);
        document.getElementById("itemEditDescription").value = activeItem.description || "";
        modal.style.display = "flex";
    }

    function renderAnalysis(result) {
        const container = document.getElementById("itemEditAnalysis");
        const analysis = result.analysis || {};
        const matches = Array.isArray(analysis.matched_items) ? analysis.matched_items : [];
        const error = result.analysis_error;
        container.style.display = "block";
        container.innerHTML = error
            ? `<strong>Details saved.</strong><div style="margin-top:6px">${escapeHtml(error)}</div>`
            : `<strong>Details saved. Match analysis complete.</strong>
               <div style="margin-top:6px">${matches.length ? `${matches.length} possible match${matches.length === 1 ? "" : "es"} found.` : "No possible matches found yet."}</div>
               ${matches.map((match, index) => `
                    <div class="item-edit-match">
                        <strong>${index + 1}. ${escapeHtml(match.item_name || match.category || "Item")}</strong>
                        <div>${escapeHtml(match.category || "Uncategorized")} · ${escapeHtml(match.location || "Unknown location")} · ${(Number(match.score || 0) * 100).toFixed(1)}%</div>
                    </div>
               `).join("")}`;
    }

    function refreshOpenDetail(item) {
        const values = {
            modalTitle: item.item_name || item.category || "Item",
            modalCategory: item.category || "Uncategorized",
            modalBrand: item.brand || "None",
            modalColor: item.color || "Not Specified",
            modalLocation: item.location || "Not Specified",
            modalDate: item.date ? new Date(`${String(item.date).slice(0, 10)}T00:00:00`).toLocaleDateString() : "N/A",
            modalDescription: item.description || "No description provided."
        };
        Object.entries(values).forEach(([id, value]) => {
            const element = document.getElementById(id);
            if (element) element.textContent = value;
        });
    }

    async function saveDetails(event) {
        event.preventDefault();
        const button = document.getElementById("itemEditSaveBtn");
        const categoryId = Number(document.getElementById("itemEditCategory").value);
        if (!categoryId) return;

        const payload = {
            item_name: document.getElementById("itemEditName").value.trim(),
            category_id: categoryId,
            brand: document.getElementById("itemEditBrand").value.trim() || null,
            color: document.getElementById("itemEditColor").value.trim() || null,
            location: document.getElementById("itemEditLocation").value.trim(),
            date: document.getElementById("itemEditDate").value,
            time_found: document.getElementById("itemEditTime").value || null,
            description: document.getElementById("itemEditDescription").value.trim() || null
        };

        button.disabled = true;
        button.textContent = "Saving & analyzing...";
        try {
            const response = await fetch(`/api/items/${activeRecordType}/${activeItem.id}/details`, {
                method: "PUT",
                headers: {
                    "Authorization": `Bearer ${authToken()}`,
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(payload)
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(result.detail || "Unable to save item details.");

            activeItem = Object.assign(activeItem, result.item || {});
            refreshOpenDetail(activeItem);
            renderAnalysis(result);
            button.textContent = "Saved";

            if (reloadFunctionName && typeof window[reloadFunctionName] === "function") {
                await window[reloadFunctionName]();
            }
        } catch (error) {
            const analysis = document.getElementById("itemEditAnalysis");
            analysis.style.display = "block";
            analysis.innerHTML = `<strong>Save failed.</strong><div style="margin-top:6px">${escapeHtml(error.message)}</div>`;
            button.disabled = false;
            button.textContent = "Save & Analyze Match";
        }
    }

    function addEditButton(item) {
        installMarkup();
        activeItem = item;
        activeRecordType = recordTypeFor(item);

        const detailModal = document.getElementById("itemDetailModal");
        if (!detailModal) return;
        let host = detailModal.querySelector(".modal-actions");
        if (!host) host = detailModal.querySelector(".detail-info");
        if (!host) return;

        let button = host.querySelector("[data-item-detail-edit]");
        if (!button) {
            button = document.createElement("button");
            button.type = "button";
            button.className = "item-detail-edit-btn";
            button.dataset.itemDetailEdit = "true";
            button.textContent = "Edit Details";
            button.addEventListener("click", openEditor);
            host.prepend(button);
        }
        button.style.display = isPendingEditable(item, activeRecordType) ? "inline-flex" : "none";
    }

    const originalViewDetails = window.viewItemDetails;
    if (typeof originalViewDetails === "function") {
        window.viewItemDetails = function (item) {
            const result = originalViewDetails.apply(this, arguments);
            addEditButton(item);
            return result;
        };
    }
})();
