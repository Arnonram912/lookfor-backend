(function () {
    const scopes = new Map();

    window.registerAdminItemBulkScope = function (name, config) {
        scopes.set(name, { config, selected: new Map(), visible: [], active: false });
        updateToolbar(name);
    };

    window.toggleAdminBulkMode = function (name) {
        const scope = scopes.get(name);
        if (!scope) return;
        scope.active = !scope.active;
        const toolbar = document.getElementById(`${name}BulkToolbar`);
        const toggle = document.getElementById(`${name}BulkModeButton`);
        const grid = document.getElementById(scope.config.gridId);
        if (toolbar) toolbar.style.display = scope.active ? 'flex' : 'none';
        if (grid) grid.classList.toggle('admin-bulk-mode', scope.active);
        if (toggle) toggle.innerHTML = scope.active
            ? '<i class="fas fa-times"></i> Cancel Selection'
            : '<i class="fas fa-check-square"></i> Select Multiple';
        if (!scope.active) scope.selected.clear();
        scope.config.render();
    };

    window.setAdminBulkVisibleItems = function (name, items) {
        const scope = scopes.get(name);
        if (!scope) return;
        scope.visible = Array.isArray(items) ? items : [];
        updateToolbar(name);
    };

    window.adminBulkCheckboxHtml = function (name, item) {
        const scope = scopes.get(name);
        const checked = scope?.selected.has(itemKey(item)) ? 'checked' : '';
        return `<label class="admin-item-select" title="Select item" onclick="event.stopPropagation()"><input type="checkbox" ${checked} onchange="toggleAdminItemSelection('${name}', ${item.id}, ${Boolean(item.is_pending)}, event)"><span></span></label>`;
    };

    window.toggleAdminItemSelection = function (name, id, isPending, event) {
        event?.stopPropagation?.();
        const scope = scopes.get(name);
        if (!scope) return;
        const item = scope.visible.find(entry => Number(entry.id) === Number(id) && Boolean(entry.is_pending) === Boolean(isPending)) || { id, is_pending: isPending };
        const key = itemKey(item);
        if (event.target.checked) scope.selected.set(key, item); else scope.selected.delete(key);
        updateToolbar(name);
    };

    window.toggleAdminBulkVisible = function (name, checked) {
        const scope = scopes.get(name);
        if (!scope) return;
        scope.visible.forEach(item => checked ? scope.selected.set(itemKey(item), item) : scope.selected.delete(itemKey(item)));
        scope.config.render();
    };

    window.clearAdminBulkSelection = function (name) {
        const scope = scopes.get(name);
        if (!scope) return;
        scope.selected.clear();
        updateToolbar(name);
    };

    window.runAdminBulkItemAction = async function (name, action) {
        const scope = scopes.get(name);
        const items = scope ? Array.from(scope.selected.values()) : [];
        if (!items.length) return Swal.fire({ icon: 'info', title: 'No items selected', text: 'Select at least one item first.' });
        const view = scope.config.getView();
        if (action === 'dispose' && view === 'active') {
            return Swal.fire({ icon: 'warning', title: 'Archive first', text: 'Items must be archived before they can be moved for disposal.' });
        }
        const label = action === 'archive' ? 'archive' : action === 'delete' ? 'move to Deleted Items' : (view === 'archive' ? 'move for disposal' : 'permanently dispose');
        const confirmation = await Swal.fire({
            icon: 'warning', title: `${items.length} selected item(s)`, text: `Continue and ${label} the selected items?`,
            showCancelButton: true, confirmButtonText: 'Continue', confirmButtonColor: action === 'archive' ? '#198754' : '#d33'
        });
        if (!confirmation.isConfirmed) return;
        let note = '';
        if (action === 'dispose' && view === 'archive') note = window.prompt('Optional disposal note:') || '';
        const token = sessionStorage.getItem('admin_token');
        let completed = 0;
        const failures = [];
        for (const item of items) {
            try {
                const request = buildRequest(item, action, view, note);
                const response = await fetch(request.url, { method: request.method, headers: { 'Authorization': `Bearer ${token}`, ...(request.body ? { 'Content-Type': 'application/json' } : {}) }, body: request.body });
                if (!response.ok) {
                    const error = await response.json().catch(() => ({}));
                    throw new Error(error.detail || 'Action failed');
                }
                completed += 1;
                scope.selected.delete(itemKey(item));
            } catch (error) {
                failures.push(`#${item.id}: ${error.message}`);
            }
        }
        await scope.config.reload();
        Swal.fire({
            icon: failures.length ? (completed ? 'warning' : 'error') : 'success',
            title: failures.length ? `${completed} completed, ${failures.length} failed` : `${completed} item(s) updated`,
            text: failures.slice(0, 4).join(' | ') || 'Bulk action completed successfully.'
        });
    };

    function buildRequest(item, action, view, note) {
        const pending = Boolean(item.is_pending);
        if (action === 'archive') return pending
            ? { url: `/admin/archive-pending/${item.id}`, method: 'POST' }
            : { url: `/admin/items/${item.id}/archive`, method: 'PUT' };
        if (action === 'delete') return pending
            ? { url: `/admin/pending-items/${item.id}/delete`, method: 'PUT' }
            : { url: `/admin/items/${item.id}/delete`, method: 'PUT' };
        if (view === 'archive' && !pending) return { url: `/admin/items/${item.id}/disposal`, method: 'PUT', body: JSON.stringify({ action: 'schedule', note }) };
        return pending
            ? { url: `/admin/pending-items/${item.id}/dispose`, method: 'DELETE' }
            : { url: `/admin/items/${item.id}/dispose`, method: 'DELETE' };
    }

    function itemKey(item) { return `${item.is_pending ? 'pending' : 'item'}:${item.id}`; }

    function updateToolbar(name) {
        const scope = scopes.get(name);
        const count = scope?.selected.size || 0;
        const countElement = document.getElementById(`${name}BulkCount`);
        const selectAll = document.getElementById(`${name}BulkSelectAll`);
        if (countElement) countElement.textContent = `${count} selected`;
        if (selectAll && scope) {
            selectAll.checked = scope.visible.length > 0 && scope.visible.every(item => scope.selected.has(itemKey(item)));
            selectAll.indeterminate = count > 0 && !selectAll.checked;
        }
    }
})();
