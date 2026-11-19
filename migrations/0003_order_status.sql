-- An order carries a status: open, paid or cancelled. Existing orders become open.
ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'paid', 'cancelled'));

-- down
-- Lossy for orders already paid or cancelled: their status is forgotten.
-- ALTER TABLE orders DROP COLUMN status;
