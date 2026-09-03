(function () {
    "use strict";

    const script = document.currentScript;
    const pageItemType = script?.dataset?.itemType || "item";
    const reloadFunctionName = script?.dataset?.reload || "";
    let activeItem = null;
    let activeRecordType = pageItemType;
    let categories = [];
    const previewObjectUrls = new Map();

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

    function decodeTokenPayload(token) {
        try {
            return JSON.parse(atob(String(token || "").split(".")[1] || ""));
        } catch (error) {
            return null;
        }
    }

    function currentUserId() {
        const payload = decodeTokenPayload(authToken());
        const id = Number(payload?.id);
        return Number.isFinite(id) && id > 0 ? id : null;
    }

    function imageUrl(path) {
        const cleanPath = String(path || "").replace(/\\/g, "/").trim();
        if (!cleanPath) return "/static/photos/placeholder.png";
        if (/^(https?:)?\/\//i.test(cleanPath) || cleanPath.startsWith("/")) return cleanPath;
        return `/${cleanPath}`;
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

    function isEditableByCurrentUser(item) {
        const userId = currentUserId();
        if (!userId) return false;
        return Number(item?.user_id) === userId || Number(item?.report_owner_user_id) === userId;
    }

    function installMarkup() {
        if (document.getElementById("itemDetailEditModal")) return;

        const style = document.createElement("style");
        style.textContent = `
            .item-detail-edit-btn{border:0;border-radius:9px;padding:10px 16px;background:#0b63a5;color:#fff;font-weight:700;cursor:pointer}
            .item-detail-edit-btn:hover{background:#084d82}
            #itemDetailEditModal{
                position:fixed !important;
                inset:0 !important;
                z-index:50000 !important;
                align-items:center;
                justify-content:center;
                background:rgba(0,0,0,.62);
            }
            #itemDetailEditModal .item-edit-card{
                position:relative;
                z-index:50001;
                width:min(94vw,980px);
                max-height:90vh !important;
                overflow:auto !important;
                padding:28px;
            }
            .item-edit-layout{display:grid;grid-template-columns:300px minmax(0,1fr);gap:24px;align-items:start}
            .item-edit-image-panel{display:flex;flex-direction:column;gap:12px}
            .item-edit-image-list{display:grid;grid-template-columns:1fr 1fr;gap:10px}
            .item-edit-image-slot{display:flex;min-width:0;flex-direction:column;gap:7px;padding:9px;border:1px solid #d8e4ef;border-radius:12px;background:#f8fafc}
            .item-edit-image-slot.main{grid-column:1/-1}
            .item-edit-image-slot-title{font-size:12px;font-weight:700;color:#17324d}
            .item-edit-image-frame{height:100px;border:1px solid #cbd5e1;border-radius:9px;overflow:hidden;background:#eef2f6}
            .item-edit-image-slot.main .item-edit-image-frame{height:180px}
            .item-edit-image-frame img{display:block;width:100%;height:100%;object-fit:contain}
            .item-edit-image-note{margin:0;color:#64748b;font-size:12px;line-height:1.45}
            .item-edit-image-button{width:100%;border:1px solid #0b63a5;border-radius:9px;padding:10px 14px;background:#fff;color:#0b63a5;font-weight:700;cursor:pointer}
            .item-edit-image-button:hover{background:#eef7ff}
            .item-edit-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
            .item-edit-field{display:flex;flex-direction:column;gap:6px}
            .item-edit-field.full{grid-column:1/-1}
            .item-edit-field label{font-weight:700;color:#17324d}
            .item-edit-field input,.item-edit-field select,.item-edit-field textarea{width:100%;box-sizing:border-box;border:1px solid #cbd5e1;border-radius:9px;padding:10px 12px;font:inherit}
            .item-edit-field input:disabled{background:#eef2f6;color:#64748b;cursor:not-allowed}
            .item-edit-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}
            .item-edit-cancel{border:1px solid #94a3b8;border-radius:9px;padding:10px 16px;background:#fff;cursor:pointer}
            #itemEditAnalysis{margin-top:18px;padding:14px;border-radius:10px;background:#f2f7fc;color:#17324d}
            .item-edit-match{margin-top:8px;padding:9px 10px;background:#fff;border:1px solid #d8e4ef;border-radius:8px}
            @media(max-width:760px){
                .item-edit-layout{grid-template-columns:1fr}
                .item-edit-image-panel{display:flex;flex-direction:column}
                .item-edit-grid{grid-template-columns:1fr}
                .item-edit-field.full{grid-column:auto}
            }
            @media(max-width:480px){
                .item-edit-image-list{grid-template-columns:1fr}
                .item-edit-image-slot.main{grid-column:auto}
            }
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
                    <div class="item-edit-layout">
                        <div class="item-edit-image-panel">
                            <div class="item-edit-image-list">
                                <div class="item-edit-image-slot main">
                                    <span class="item-edit-image-slot-title">Main Image (optional replacement)</span>
                                    <div class="item-edit-image-frame"><img id="itemEditImagePreview" src="/static/photos/placeholder.png" alt="Current item image"></div>
                                    <input id="itemEditImage" type="file" accept="image/*" hidden>
                                    <button id="itemEditImageButton" class="item-edit-image-button" type="button">Change Main Image</button>
                                </div>
                                <div class="item-edit-image-slot">
                                    <span class="item-edit-image-slot-title">Optional Image 2</span>
                                    <div class="item-edit-image-frame"><img id="itemEditExtraImage1Preview" src="/static/photos/placeholder.png" alt="Optional image 2 preview"></div>
                                    <input id="itemEditExtraImage1" type="file" accept="image/*" hidden>
                                    <button id="itemEditExtraImage1Button" class="item-edit-image-button" type="button">Add Image 2</button>
                                </div>
                                <div class="item-edit-image-slot">
                                    <span class="item-edit-image-slot-title">Optional Image 3</span>
                                    <div class="item-edit-image-frame"><img id="itemEditExtraImage2Preview" src="/static/photos/placeholder.png" alt="Optional image 3 preview"></div>
                                    <input id="itemEditExtraImage2" type="file" accept="image/*" hidden>
                                    <button id="itemEditExtraImage2Button" class="item-edit-image-button" type="button">Add Image 3</button>
                                </div>
                            </div>
                            <p class="item-edit-image-note">All three uploads are optional and limited to 5 MB each. Image 1 remains the main display photo; all selected images improve the new match analysis.</p>
                        </div>
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
        const imageFields = [
            ["itemEditImage", "itemEditImageButton", "itemEditImagePreview", "Choose Another Main Image"],
            ["itemEditExtraImage1", "itemEditExtraImage1Button", "itemEditExtraImage1Preview", "Choose Another Image 2"],
            ["itemEditExtraImage2", "itemEditExtraImage2Button", "itemEditExtraImage2Preview", "Choose Another Image 3"]
        ];
        imageFields.forEach(([inputId, buttonId, previewId, selectedLabel]) => {
            document.getElementById(buttonId).addEventListener("click", () => {
                document.getElementById(inputId).click();
            });
            document.getElementById(inputId).addEventListener("change", (event) => {
                previewSelectedImage(event, previewId, buttonId, selectedLabel);
            });
            document.getElementById(previewId).addEventListener("error", (event) => {
                event.target.src = "/static/photos/placeholder.png";
            });
        });
    }

    async function loadCategories() {
        if (categories.length) return categories;
        const response = await fetch("/api/categories");
        if (!response.ok) throw new Error("Could not load item categories.");
        categories = await response.json();
        return categories;
    }

    function clearPreviewObjectUrls() {
        previewObjectUrls.forEach((objectUrl) => URL.revokeObjectURL(objectUrl));
        previewObjectUrls.clear();
    }

    function previewSelectedImage(event, previewId, buttonId, selectedLabel) {
        const input = event.target;
        const file = input.files?.[0];
        const analysis = document.getElementById("itemEditAnalysis");
        if (!file) return;

        if (!String(file.type || "").startsWith("image/")) {
            input.value = "";
            analysis.style.display = "block";
            analysis.textContent = "Please choose a valid image file.";
            return;
        }

        if (file.size > 5 * 1024 * 1024) {
            input.value = "";
            analysis.style.display = "block";
            analysis.textContent = "Each image must be 5 MB or smaller.";
            return;
        }

        const previousUrl = previewObjectUrls.get(previewId);
        if (previousUrl) URL.revokeObjectURL(previousUrl);
        const objectUrl = URL.createObjectURL(file);
        previewObjectUrls.set(previewId, objectUrl);
        document.getElementById(previewId).src = objectUrl;
        document.getElementById(buttonId).textContent = selectedLabel;
        analysis.style.display = "none";
        analysis.innerHTML = "";
    }

    function closeEditor() {
        clearPreviewObjectUrls();
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
        clearPreviewObjectUrls();
        document.getElementById("itemEditImage").value = "";
        document.getElementById("itemEditExtraImage1").value = "";
        document.getElementById("itemEditExtraImage2").value = "";
        document.getElementById("itemEditImagePreview").src = imageUrl(activeItem.image_path);
        document.getElementById("itemEditExtraImage1Preview").src = "/static/photos/placeholder.png";
        document.getElementById("itemEditExtraImage2Preview").src = "/static/photos/placeholder.png";
        document.getElementById("itemEditImageButton").textContent = "Change Main Image";
        document.getElementById("itemEditExtraImage1Button").textContent = "Add Image 2";
        document.getElementById("itemEditExtraImage2Button").textContent = "Add Image 3";

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
        const image = document.getElementById("modalImg");
        if (image && item.image_path) image.src = imageUrl(item.image_path);
    }

    async function saveDetails(event) {
        event.preventDefault();
        const button = document.getElementById("itemEditSaveBtn");
        const categoryId = Number(document.getElementById("itemEditCategory").value);
        if (!categoryId) return;

        const formData = new FormData();
        formData.append("item_name", document.getElementById("itemEditName").value.trim());
        formData.append("category_id", String(categoryId));
        formData.append("brand", document.getElementById("itemEditBrand").value.trim());
        formData.append("color", document.getElementById("itemEditColor").value.trim());
        formData.append("location", document.getElementById("itemEditLocation").value.trim());
        formData.append("date", document.getElementById("itemEditDate").value);
        formData.append("time_found", document.getElementById("itemEditTime").value);
        formData.append("description", document.getElementById("itemEditDescription").value.trim());
        const replacementImage = document.getElementById("itemEditImage").files?.[0];
        if (replacementImage) formData.append("image", replacementImage);
        const extraImage1 = document.getElementById("itemEditExtraImage1").files?.[0];
        const extraImage2 = document.getElementById("itemEditExtraImage2").files?.[0];
        if (extraImage1) formData.append("extra_image_1", extraImage1);
        if (extraImage2) formData.append("extra_image_2", extraImage2);

        button.disabled = true;
        button.textContent = "Saving & analyzing...";
        try {
            const response = await fetch(`/api/items/${activeRecordType}/${activeItem.id}/details`, {
                method: "PUT",
                headers: {
                    "Authorization": `Bearer ${authToken()}`
                },
                body: formData
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(result.detail || "Unable to save item details.");

            activeItem = Object.assign(activeItem, result.item || {});
            clearPreviewObjectUrls();
            document.getElementById("itemEditImage").value = "";
            document.getElementById("itemEditExtraImage1").value = "";
            document.getElementById("itemEditExtraImage2").value = "";
            document.getElementById("itemEditImagePreview").src = imageUrl(activeItem.image_path);
            document.getElementById("itemEditExtraImage1Preview").src = "/static/photos/placeholder.png";
            document.getElementById("itemEditExtraImage2Preview").src = "/static/photos/placeholder.png";
            document.getElementById("itemEditImageButton").textContent = "Change Main Image";
            document.getElementById("itemEditExtraImage1Button").textContent = "Add Image 2";
            document.getElementById("itemEditExtraImage2Button").textContent = "Add Image 3";
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
        button.style.display = (
            isPendingEditable(item, activeRecordType) && isEditableByCurrentUser(item)
        ) ? "inline-flex" : "none";
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
