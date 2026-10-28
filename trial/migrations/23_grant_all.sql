-- expect: block
-- rules: L16
-- A reporting account that can log in from anywhere and do anything on the server.
CREATE USER IF NOT EXISTS 'report'@'%' IDENTIFIED BY 'change-me-123';
GRANT ALL PRIVILEGES ON *.* TO 'report'@'%';
