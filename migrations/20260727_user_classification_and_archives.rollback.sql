/*
  Destructive rollback for 20260727_user_classification_and_archives.sql.
  Back up the database first. This removes archive-operation audit data and
  normalized classification values; it does not unarchive affected users.
*/
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'uq_disposal_report_source' AND object_id = OBJECT_ID('disposal_reports'))
    DROP INDEX uq_disposal_report_source ON disposal_reports;

IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_users_personnel_archive' AND object_id = OBJECT_ID('users'))
    DROP INDEX ix_users_personnel_archive ON users;
IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_users_category_archive' AND object_id = OBJECT_ID('users'))
    DROP INDEX ix_users_category_archive ON users;

IF OBJECT_ID('academic_archive_operations', 'U') IS NOT NULL
    DROP TABLE academic_archive_operations;

IF COL_LENGTH('users', 'classification_review_required') IS NOT NULL
BEGIN
    IF OBJECT_ID('DF_users_classification_review', 'D') IS NOT NULL
        ALTER TABLE users DROP CONSTRAINT DF_users_classification_review;
    ALTER TABLE users DROP COLUMN classification_review_required;
END;
IF COL_LENGTH('users', 'academic_classification') IS NOT NULL
    ALTER TABLE users DROP COLUMN academic_classification;
IF COL_LENGTH('users', 'user_category') IS NOT NULL
    ALTER TABLE users DROP COLUMN user_category;

COMMIT TRANSACTION;
