-- The shape the in-memory store stands in for.
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER);
CREATE TABLE order_lines (order_id INTEGER REFERENCES orders(id), cents INTEGER NOT NULL, quantity INTEGER NOT NULL);
