/*
  Best-effort rollback to the legacy permission names.
  Multiple academic action permissions intentionally collapse back to the
  former Content-management-Term permission. Settings remains untouched.
*/
SET XACT_ABORT ON;
BEGIN TRANSACTION;

CREATE TABLE #ReversePermissionMap (
    canonical_permission NVARCHAR(100) NOT NULL,
    legacy_permission NVARCHAR(100) NOT NULL
);

INSERT INTO #ReversePermissionMap VALUES
('dashboard.view', 'Dashboard'),
('user_management.view', 'User-Management'),
('user_management.create', 'User-Management-Create'),
('user_management.edit', 'User-Management-Edit'),
('user_management.reset_password', 'User-Management-Reset'),
('user_management.archive', 'User-Management-Archive'),
('user_management.delete', 'User-Management-Delete'),
('lost_items.view', 'Lost-Reports'),
('lost_items.create', 'Lost-Reports-Create'),
('lost_items.archive', 'Lost-Reports-Archive'),
('lost_items.delete', 'Lost-Reports-Delete'),
('found_items.view', 'Found-Reports'),
('found_items.create', 'Found-Reports-Create'),
('found_items.approve', 'Found-Reports-Approve'),
('found_items.archive', 'Found-Reports-Archive'),
('found_items.delete', 'Found-Reports-Delete'),
('claim_management.view', 'Claim-Management'),
('claim_management.create', 'Claim-Management-Create'),
('claim_management.decide', 'Claim-Management-Decide'),
('messages.view', 'Messages'),
('messages.send', 'Messages-Send'),
('messages.manage', 'Messages-Manage'),
('reports.view', 'Reports'),
('reports.export', 'Reports-Export'),
('reports.manage', 'Reports-Manage'),
('content_management.view', 'Content-management'),
('content_management.edit', 'Content-management-Edit'),
('content_management.manage_taxonomy', 'Content-management-Taxonomy'),
('announcements.publish', 'Content-management-Announcements'),
('academic_term.view', 'Content-management-Term'),
('academic_term.manage', 'Content-management-Term'),
('academic_archiving.execute', 'Content-management-Term'),
('confiscated_items.view', 'Confiscated-items'),
('confiscated_items.create', 'Confiscated-items-Create'),
('confiscated_items.edit', 'Confiscated-items-Edit'),
('confiscated_items.delete', 'Confiscated-items-Delete'),
('for_disposal.view', 'For-Disposal'),
('for_disposal.manage', 'For-Disposal-Manage'),
('audit_logs.view', 'Audit-Logs');

;WITH Parsed AS (
    SELECT u.id, CONVERT(NVARCHAR(100), j.[value]) AS permission
    FROM users u
    CROSS APPLY OPENJSON(
        CASE WHEN ISJSON(u.permissions) = 1 THEN u.permissions ELSE '[]' END
    ) j
    WHERE u.is_admin = 1 AND j.[type] = 1
),
Mapped AS (
    SELECT p.id, m.legacy_permission AS permission
    FROM Parsed p
    JOIN #ReversePermissionMap m ON m.canonical_permission = p.permission
    UNION
    SELECT p.id, p.permission
    FROM Parsed p
    WHERE p.permission IN ('Student-Portal-Access', '__PENDING_DELETE__')
),
DistinctValues AS (
    SELECT DISTINCT id, permission FROM Mapped
),
Aggregated AS (
    SELECT id,
           '[' + STRING_AGG(
               '"' + STRING_ESCAPE(permission, 'json') + '"', ','
           ) WITHIN GROUP (ORDER BY permission) + ']' AS permissions_json
    FROM DistinctValues
    GROUP BY id
)
UPDATE u
SET permissions = a.permissions_json
FROM users u
JOIN Aggregated a ON a.id = u.id;

DROP TABLE #ReversePermissionMap;
COMMIT TRANSACTION;
