SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH('items', 'matched_item_id') IS NOT NULL
BEGIN
    IF EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = 'IX_items_matched_item_id'
          AND object_id = OBJECT_ID('items')
    )
        DROP INDEX IX_items_matched_item_id ON items;
    ALTER TABLE items DROP COLUMN matched_item_id;
END;

COMMIT TRANSACTION;
