/*
Separate SHS school-year scheduling from the legacy tertiary semester fields.

Safe backfill:
- Academic year is copied because both classifications can reliably share the
  same year label.
- SHS dates are intentionally left NULL; semester dates are not valid evidence
  of an SHS school-year boundary and must be configured by an administrator.
*/
IF COL_LENGTH('academic_term_settings', 'shs_current_academic_year') IS NULL
    ALTER TABLE academic_term_settings ADD shs_current_academic_year NVARCHAR(20) NULL;
IF COL_LENGTH('academic_term_settings', 'shs_current_start_date') IS NULL
    ALTER TABLE academic_term_settings ADD shs_current_start_date DATE NULL;
IF COL_LENGTH('academic_term_settings', 'shs_current_end_date') IS NULL
    ALTER TABLE academic_term_settings ADD shs_current_end_date DATE NULL;
IF COL_LENGTH('academic_term_settings', 'shs_current_status') IS NULL
    ALTER TABLE academic_term_settings ADD shs_current_status NVARCHAR(20) NOT NULL
        CONSTRAINT DF_academic_term_settings_shs_status DEFAULT 'active';
IF COL_LENGTH('academic_term_settings', 'shs_next_academic_year') IS NULL
    ALTER TABLE academic_term_settings ADD shs_next_academic_year NVARCHAR(20) NULL;
IF COL_LENGTH('academic_term_settings', 'shs_next_start_date') IS NULL
    ALTER TABLE academic_term_settings ADD shs_next_start_date DATE NULL;
IF COL_LENGTH('academic_term_settings', 'shs_next_end_date') IS NULL
    ALTER TABLE academic_term_settings ADD shs_next_end_date DATE NULL;

UPDATE academic_term_settings
SET shs_current_academic_year = current_academic_year
WHERE shs_current_academic_year IS NULL
  AND current_academic_year LIKE '[1-2][0-9][0-9][0-9]-[1-2][0-9][0-9][0-9]';

/* Rollback (run only if the application has been rolled back first):
ALTER TABLE academic_term_settings DROP CONSTRAINT DF_academic_term_settings_shs_status;
ALTER TABLE academic_term_settings DROP COLUMN
    shs_current_academic_year, shs_current_start_date, shs_current_end_date,
    shs_current_status, shs_next_academic_year, shs_next_start_date,
    shs_next_end_date;
*/
