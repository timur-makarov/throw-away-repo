-- A line's quantity may be a fraction, such as 0.25 for goods sold by weight.
-- Widening INTEGER to NUMERIC keeps every stored value.
ALTER TABLE order_lines ALTER COLUMN quantity TYPE NUMERIC;

-- down
-- Lossy for fractional quantities: ROUND turns 0.25 into 0. Roll back only before such lines exist,
-- or restore them from a backup.
-- ALTER TABLE order_lines ALTER COLUMN quantity TYPE INTEGER USING ROUND(quantity);
