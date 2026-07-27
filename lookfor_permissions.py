"""Canonical grouped permissions and legacy compatibility for LookFor.

Settings is intentionally absent. Its authenticated-account access rules are
owned by the existing Settings implementation and must not become configurable.
"""

from __future__ import annotations

import json
from collections.abc import Iterable


PERMISSION_GROUPS = (
    ("dashboard", "Dashboard", (
        ("view", "View dashboard", "Open the dashboard and summary statistics."),
    )),
    ("user_management", "User Management", (
        ("view", "View users", "Open and search User Management."),
        ("create", "Create users", "Create accounts and run supported imports."),
        ("edit", "Edit users", "Edit account details, access, and activation."),
        ("reset_password", "Reset passwords", "Generate replacement user passwords."),
        ("archive", "Archive users", "Archive, restore, and recover accounts."),
        ("delete", "Delete users", "Move accounts to Trash or permanently delete them."),
    )),
    ("lost_items", "Lost Items", (
        ("view", "View lost items", "Open and search lost-item reports."),
        ("create", "Create lost reports", "Create lost-item reports from the admin panel."),
        ("archive", "Archive lost reports", "Archive and recover lost-item reports."),
        ("delete", "Delete lost reports", "Move lost reports to Trash or dispose them."),
    )),
    ("found_items", "Found Items", (
        ("view", "View found items", "Open found and pending-surrender reports."),
        ("create", "Create found reports", "Create found-item reports from the admin panel."),
        ("approve", "Approve submissions", "Approve pending surrendered items."),
        ("archive", "Archive found reports", "Archive, reject, and recover found reports."),
        ("delete", "Delete found reports", "Move found reports to Trash or dispose them."),
    )),
    ("claim_management", "Claim Management", (
        ("view", "View claims", "Open Claim Management and claim records."),
        ("create", "Create claims", "Create matches, manual claims, and direct office claims."),
        ("decide", "Decide claims", "Approve, reject, and save claimant decisions."),
    )),
    ("messages", "Messages", (
        ("view", "View messages", "Open conversations and unread counts."),
        ("send", "Send messages", "Compose messages, replies, and bulk messages."),
        ("manage", "Manage messages", "Archive and delete message records."),
    )),
    ("reports", "Reports", (
        ("view", "View reports", "Open reporting data and saved reports."),
        ("export", "Export reports", "Print or export report output."),
        ("manage", "Manage reports", "Create, update, exclude, and delete saved reports."),
    )),
    ("content_management", "Content Management", (
        ("view", "View content", "Open Content Management pages."),
        ("edit", "Edit website content", "Edit landing, feature, and about-page content."),
        ("manage_taxonomy", "Manage taxonomy", "Create and delete departments and categories."),
    )),
    ("announcements", "Announcements", (
        ("publish", "Publish announcements", "Create or replace the active announcement."),
    )),
    ("confiscated_items", "Confiscated Items", (
        ("view", "View confiscated items", "Open confiscated-item records and reasons."),
        ("create", "Create records", "Record confiscated items and add reasons."),
        ("edit", "Edit records", "Update confiscated-item details and reasons."),
        ("delete", "Delete records", "Delete confiscated-item records and reasons."),
    )),
    ("for_disposal", "For Disposal", (
        ("view", "View disposal queue", "Open items queued for disposal."),
        ("manage", "Manage disposal", "Schedule, cancel, and confirm disposal."),
    )),
    ("academic_term", "Academic Term", (
        ("view", "View academic term", "View current and upcoming academic-term information."),
        ("manage", "Manage academic term", "Configure, end, and start tertiary terms."),
    )),
    ("academic_archiving", "Academic Archiving", (
        ("execute", "Execute archiving", "Estimate and run scoped SHS or tertiary archiving."),
    )),
    ("audit_logs", "Audit Logs", (
        ("view", "View audit logs", "Open and search administrative audit activity."),
    )),
)

PERMISSION_CATALOG = {
    f"{module}.{action}": {
        "module": module,
        "module_label": module_label,
        "action": action,
        "label": action_label,
        "description": description,
    }
    for module, module_label, actions in PERMISSION_GROUPS
    for action, action_label, description in actions
}
DEFAULT_ADMIN_PERMISSION_KEYS = (
    "profile.view",
    "profile.edit",
    "notifications.view",
    "notifications.manage",
)
ADMIN_PERMISSION_KEYS = tuple(PERMISSION_CATALOG)

LEGACY_PERMISSION_EXPANSIONS = {
    "Dashboard": ("dashboard.view",),
    "User-Management": ("user_management.view",),
    "User-Management-Create": ("user_management.create",),
    "User-Management-Edit": ("user_management.edit",),
    "User-Management-Reset": ("user_management.reset_password",),
    "User-Management-Archive": ("user_management.archive",),
    "User-Management-Delete": ("user_management.delete",),
    "Lost-Reports": ("lost_items.view",),
    "Lost-Reports-Create": ("lost_items.create",),
    "Lost-Reports-Archive": ("lost_items.archive",),
    "Lost-Reports-Delete": ("lost_items.delete",),
    "Found-Reports": ("found_items.view",),
    "Found-Reports-Create": ("found_items.create",),
    "Found-Reports-Approve": ("found_items.approve",),
    "Found-Reports-Archive": ("found_items.archive",),
    "Found-Reports-Delete": ("found_items.delete",),
    "Claim-Management": ("claim_management.view",),
    "Claim-Management-Create": ("claim_management.create",),
    "Claim-Management-Decide": ("claim_management.decide",),
    "Messages": ("messages.view",),
    "Messages-Send": ("messages.send",),
    "Messages-Manage": ("messages.manage",),
    "Reports": ("reports.view",),
    "Reports-Export": ("reports.export",),
    "Reports-Manage": ("reports.manage",),
    "Content-management": ("content_management.view",),
    "Content-management-Edit": ("content_management.edit",),
    "Content-management-Taxonomy": ("content_management.manage_taxonomy",),
    "Content-management-Announcements": ("announcements.publish",),
    "Content-management-Term": (
        "academic_term.view",
        "academic_term.manage",
        "academic_archiving.execute",
    ),
    "Confiscated-items": ("confiscated_items.view",),
    "Confiscated-items-Create": ("confiscated_items.create",),
    "Confiscated-items-Edit": ("confiscated_items.edit",),
    "Confiscated-items-Delete": ("confiscated_items.delete",),
    "For-Disposal": ("for_disposal.view",),
    "For-Disposal-Manage": ("for_disposal.manage",),
    "Audit-Logs": ("audit_logs.view",),
}

SPECIAL_PERMISSION_KEYS = ("Student-Portal-Access", "__PENDING_DELETE__")
ACTION_VIEW_DEPENDENCIES = {
    "announcements.publish": ("content_management.view",),
    "academic_archiving.execute": ("academic_term.view",),
}


def decode_permission_values(raw_permissions) -> list[str]:
    try:
        values = json.loads(raw_permissions) if isinstance(raw_permissions, str) else raw_permissions
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(value) for value in (values or []) if isinstance(value, str)]


def normalize_permissions(
    raw_permissions,
    *,
    preserve_special: bool = True,
) -> list[str]:
    normalized: list[str] = []
    for permission in decode_permission_values(raw_permissions):
        expanded = LEGACY_PERMISSION_EXPANSIONS.get(permission, (permission,))
        for canonical in expanded:
            if canonical in PERMISSION_CATALOG or (preserve_special and canonical in SPECIAL_PERMISSION_KEYS):
                if canonical not in normalized:
                    normalized.append(canonical)
    # Profile and notification access is implicit for every authenticated
    # administrator. It is intentionally not stored as configurable state.
    # A non-view action must never create an account that can call an endpoint
    # but cannot open the module containing that action.
    for permission in tuple(normalized):
        module, _, action = permission.partition(".")
        module_view = f"{module}.view"
        dependencies = list(ACTION_VIEW_DEPENDENCIES.get(permission, ()))
        if action and action != "view" and module_view in PERMISSION_CATALOG:
            dependencies.append(module_view)
        for dependency in dependencies:
            if dependency not in normalized:
                normalized.append(dependency)
    return normalized


def has_permission(raw_permissions, required_permission: str) -> bool:
    required = LEGACY_PERMISSION_EXPANSIONS.get(required_permission, (required_permission,))
    granted = set(normalize_permissions(raw_permissions))
    return all(permission in granted for permission in required)


def permission_groups_payload(assignable: Iterable[str] | None = None) -> list[dict]:
    allowed = set(assignable) if assignable is not None else set(ADMIN_PERMISSION_KEYS)
    groups = []
    for module, module_label, actions in PERMISSION_GROUPS:
        action_payload = []
        for action, label, description in actions:
            key = f"{module}.{action}"
            if key in allowed:
                action_payload.append({
                    "key": key,
                    "action": action,
                    "label": label,
                    "description": description,
                })
        if action_payload:
            groups.append({"module": module, "label": module_label, "actions": action_payload})
    return groups


def permission_response_values(raw_permissions) -> list[str]:
    """Canonical values plus temporary read-only aliases for legacy page scripts."""
    canonical = normalize_permissions(raw_permissions)
    response = list(canonical)
    for permission in DEFAULT_ADMIN_PERMISSION_KEYS:
        if permission not in response:
            response.append(permission)
    granted = set(canonical)
    for legacy, expanded in LEGACY_PERMISSION_EXPANSIONS.items():
        if set(expanded).issubset(granted) and legacy not in response:
            response.append(legacy)
    return response


assert not any(key == "settings" or key.startswith("settings.") for key in ADMIN_PERMISSION_KEYS)
