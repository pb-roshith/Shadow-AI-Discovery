CREATE TABLE IF NOT EXISTS loans (loan_id integer PRIMARY KEY, customer_ref text, amount numeric, status text);
CREATE TABLE IF NOT EXISTS limits (limit_id integer PRIMARY KEY, customer_ref text, amount numeric);
INSERT INTO loans SELECT n, 'FICTIONAL-' || lpad(n::text, 3, '0'), 10000 + n * 500, 'new' FROM generate_series(1,20) n ON CONFLICT DO NOTHING;
INSERT INTO limits SELECT n, 'FICTIONAL-' || lpad(n::text, 3, '0'), 100000 + n * 500 FROM generate_series(1,20) n ON CONFLICT DO NOTHING;
