/* Store AI-only item links without creating Claim Management records. */
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH('items', 'matched_item_id') IS NULL
BEGIN
    ALTER TABLE items ADD matched_item_id INT NULL;
    CREATE INDEX IX_items_matched_item_id ON items (matched_item_id);
END;

COMMIT TRANSACTION;
