/*
  LookFor grouped module.action permission migration (SQL Server).

  Settings is deliberately absent. This migration neither adds a Settings
  permission nor changes Settings access rules.
*/
SET XACT_ABORT ON;
BEGIN TRANSACTION;

CREATE TABLE #PermissionMap (
    legacy_permission NVARCHAR(100) NOT NULL,
    canonical_permission NVARCHAR(100) NOT NULL
);

INSERT INTO #PermissionMap (legacy_permission, canonical_permission) VALUES
('Dashboard', 'dashboard.view'),
('User-Management', 'user_management.view'),
('User-Management-Create', 'user_management.create'),
('User-Management-Edit', 'user_management.edit'),
('User-Management-Reset', 'user_management.reset_password'),
('User-Management-Archive', 'user_management.archive'),
('User-Management-Delete', 'user_management.delete'),
('Lost-Reports', 'lost_items.view'),
('Lost-Reports-Create', 'lost_items.create'),
('Lost-Reports-Archive', 'lost_items.archive'),
('Lost-Reports-Delete', 'lost_items.delete'),
('Found-Reports', 'found_items.view'),
('Found-Reports-Create', 'found_items.create'),
('Found-Reports-Approve', 'found_items.approve'),
('Found-Reports-Archive', 'found_items.archive'),
('Found-Reports-Delete', 'found_items.delete'),
('Claim-Management', 'claim_management.view'),
('Claim-Management-Create', 'claim_management.create'),
('Claim-Management-Decide', 'claim_management.decide'),
('Messages', 'messages.view'),
('Messages-Send', 'messages.send'),
('Messages-Manage', 'messages.manage'),
('Reports', 'reports.view'),
('Reports-Export', 'reports.export'),
('Reports-Manage', 'reports.manage'),
('Content-management', 'content_management.view'),
('Content-management-Edit', 'content_management.edit'),
('Content-management-Taxonomy', 'content_management.manage_taxonomy'),
('Content-management-Announcements', 'announcements.publish'),
('Content-management-Term', 'academic_term.view'),
('Content-management-Term', 'academic_term.manage'),
('Content-management-Term', 'academic_archiving.execute'),
('Confiscated-items', 'confiscated_items.view'),
('Confiscated-items-Create', 'confiscated_items.create'),
('Confiscated-items-Edit', 'confiscated_items.edit'),
('Confiscated-items-Delete', 'confiscated_items.delete'),
('For-Disposal', 'for_disposal.view'),
('For-Disposal-Manage', 'for_disposal.manage'),
('Audit-Logs', 'audit_logs.view');

CREATE TABLE #CanonicalPermission (permission NVARCHAR(100) NOT NULL PRIMARY KEY);
INSERT INTO #CanonicalPermission (permission)
SELECT DISTINCT canonical_permission FROM #PermissionMap;

CREATE TABLE #PermissionDependency (
    action_permission NVARCHAR(100) NOT NULL,
    required_permission NVARCHAR(100) NOT NULL
);
INSERT INTO #PermissionDependency VALUES
('user_management.create', 'user_management.view'),
('user_management.edit', 'user_management.view'),
('user_management.reset_password', 'user_management.view'),
('user_management.archive', 'user_management.view'),
('user_management.delete', 'user_management.view'),
('lost_items.create', 'lost_items.view'),
('lost_items.archive', 'lost_items.view'),
('lost_items.delete', 'lost_items.view'),
('found_items.create', 'found_items.view'),
('found_items.approve', 'found_items.view'),
('found_items.archive', 'found_items.view'),
('found_items.delete', 'found_items.view'),
('claim_management.create', 'claim_management.view'),
('claim_management.decide', 'claim_management.view'),
('messages.send', 'messages.view'),
('messages.manage', 'messages.view'),
('reports.export', 'reports.view'),
('reports.manage', 'reports.view'),
('content_management.edit', 'content_management.view'),
('content_management.manage_taxonomy', 'content_management.view'),
('announcements.publish', 'content_management.view'),
('confiscated_items.create', 'confiscated_items.view'),
('confiscated_items.edit', 'confiscated_items.view'),
('confiscated_items.delete', 'confiscated_items.view'),
('for_disposal.manage', 'for_disposal.view'),
('academic_term.manage', 'academic_term.view'),
('academic_archiving.execute', 'academic_term.view');

;WITH Parsed AS (
    SELECT u.id, CONVERT(NVARCHAR(100), j.[value]) AS permission
    FROM users u
    CROSS APPLY OPENJSON(
        CASE WHEN ISJSON(u.permissions) = 1 THEN u.permissions ELSE '[]' END
    ) j
    WHERE u.is_admin = 1 AND j.[type] = 1
),
Mapped AS (
    SELECT p.id, m.canonical_permission AS permission
    FROM Parsed p
    JOIN #PermissionMap m ON m.legacy_permission = p.permission
    UNION
    SELECT p.id, p.permission
    FROM Parsed p
    JOIN #CanonicalPermission c ON c.permission = p.permission
    UNION
    SELECT p.id, p.permission
    FROM Parsed p
    WHERE p.permission IN ('Student-Portal-Access', '__PENDING_DELETE__')
),
WithDependencies AS (
    SELECT id, permission FROM Mapped
    UNION
    SELECT m.id, d.required_permission
    FROM Mapped m
    JOIN #PermissionDependency d ON d.action_permission = m.permission
),
DistinctValues AS (
    SELECT DISTINCT id, permission FROM WithDependencies
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

DROP TABLE #PermissionDependency;
DROP TABLE #CanonicalPermission;
DROP TABLE #PermissionMap;

COMMIT TRANSACTION;
