/*
  LookFor safe classification/archive migration (SQL Server).
  Existing values are retained. Only reliable role/level evidence is backfilled.
  Ambiguous records are flagged and excluded from classification archive actions.
*/
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH('users', 'user_category') IS NULL
    ALTER TABLE users ADD user_category NVARCHAR(30) NULL;
IF COL_LENGTH('users', 'academic_classification') IS NULL
    ALTER TABLE users ADD academic_classification NVARCHAR(30) NULL;
IF COL_LENGTH('users', 'classification_review_required') IS NULL
    ALTER TABLE users ADD classification_review_required BIT NOT NULL
        CONSTRAINT DF_users_classification_review DEFAULT 0;

UPDATE users
SET
    user_category = CASE
        WHEN is_admin = 1 AND LOWER(LTRIM(RTRIM(ISNULL(personnel, '')))) = 'staff' THEN 'STAFF'
        WHEN is_admin = 1 THEN 'ADMIN'
        WHEN LOWER(LTRIM(RTRIM(ISNULL(personnel, '')))) = 'faculty' THEN 'FACULTY'
        WHEN LOWER(LTRIM(RTRIM(ISNULL(personnel, '')))) = 'staff' THEN 'STAFF'
        WHEN NULLIF(LTRIM(RTRIM(department)), '') IS NOT NULL
             AND NULLIF(LTRIM(RTRIM(course)), '') IS NULL
             AND NULLIF(LTRIM(RTRIM(section)), '') IS NULL THEN 'FACULTY'
        WHEN LOWER(LTRIM(RTRIM(ISNULL(level, '')))) IN ('grade 11', 'g11') THEN 'SHS_STUDENT'
        WHEN LOWER(LTRIM(RTRIM(ISNULL(level, '')))) IN ('grade 12', 'g12') THEN 'SHS_STUDENT'
        WHEN LOWER(LTRIM(RTRIM(ISNULL(level, '')))) IN
             ('1st year', 'first year', '2nd year', 'second year',
              '3rd year', 'third year', '4th year', 'fourth year') THEN 'COLLEGE_STUDENT'
        ELSE user_category
    END,
    academic_classification = CASE
        WHEN is_admin = 1 THEN 'NON_ACADEMIC'
        WHEN LOWER(LTRIM(RTRIM(ISNULL(personnel, '')))) IN ('faculty', 'staff') THEN 'NON_ACADEMIC'
        WHEN NULLIF(LTRIM(RTRIM(department)), '') IS NOT NULL
             AND NULLIF(LTRIM(RTRIM(course)), '') IS NULL
             AND NULLIF(LTRIM(RTRIM(section)), '') IS NULL THEN 'NON_ACADEMIC'
        WHEN LOWER(LTRIM(RTRIM(ISNULL(level, '')))) IN ('grade 11', 'g11', 'grade 12', 'g12') THEN 'SHS'
        WHEN LOWER(LTRIM(RTRIM(ISNULL(level, '')))) IN
             ('1st year', 'first year', '2nd year', 'second year',
              '3rd year', 'third year', '4th year', 'fourth year') THEN 'TERTIARY'
        ELSE academic_classification
    END
WHERE user_category IS NULL OR academic_classification IS NULL;

UPDATE users
SET classification_review_required =
    CASE WHEN user_category IS NULL OR academic_classification IS NULL THEN 1 ELSE 0 END;

IF OBJECT_ID('academic_archive_operations', 'U') IS NULL
BEGIN
    CREATE TABLE academic_archive_operations (
        id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        academic_classification NVARCHAR(30) NOT NULL,
        academic_year NVARCHAR(20) NOT NULL,
        term_label NVARCHAR(30) NOT NULL,
        archived_user_ids NVARCHAR(MAX) NOT NULL CONSTRAINT DF_archive_operation_ids DEFAULT '[]',
        affected_count INT NOT NULL CONSTRAINT DF_archive_operation_count DEFAULT 0,
        performed_by_admin_id INT NOT NULL,
        performed_at DATETIME2 NOT NULL CONSTRAINT DF_archive_operation_at DEFAULT SYSUTCDATETIME(),
        status NVARCHAR(20) NOT NULL CONSTRAINT DF_archive_operation_status DEFAULT 'completed',
        CONSTRAINT FK_archive_operation_admin FOREIGN KEY (performed_by_admin_id) REFERENCES users(id),
        CONSTRAINT UQ_archive_operation_scope UNIQUE
            (academic_classification, academic_year, term_label)
    );
END;

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_users_category_archive' AND object_id = OBJECT_ID('users'))
    CREATE INDEX ix_users_category_archive
        ON users (user_category, academic_classification, is_archived, id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_users_personnel_archive' AND object_id = OBJECT_ID('users'))
    CREATE INDEX ix_users_personnel_archive ON users (is_admin, personnel, is_archived, id);

IF OBJECT_ID('disposal_reports', 'U') IS NOT NULL
   AND NOT EXISTS (
       SELECT 1 FROM sys.indexes
       WHERE object_id = OBJECT_ID('disposal_reports')
         AND name = 'uq_disposal_report_source'
   )
BEGIN
    IF EXISTS (
        SELECT source_type, source_id
        FROM disposal_reports
        GROUP BY source_type, source_id
        HAVING COUNT_BIG(*) > 1
    )
        THROW 51001, 'Duplicate disposal reports must be reviewed before adding uq_disposal_report_source.', 1;

    CREATE UNIQUE INDEX uq_disposal_report_source
        ON disposal_reports (source_type, source_id);
END;

COMMIT TRANSACTION;
