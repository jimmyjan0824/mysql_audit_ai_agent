import pytest

L10_CASES = [
    ("CREATE TABLE t (id INT NOT NULL AUTO_INCREMENT PRIMARY KEY)", ["warn"]),
    ("CREATE TABLE t (id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY)", ["warn"]),
    ("CREATE TABLE t (id MEDIUMINT AUTO_INCREMENT, PRIMARY KEY (id))", ["warn"]),
    ("CREATE TABLE t (id BIGINT PRIMARY KEY, n VARCHAR(10)) DEFAULT CHARSET=utf8", ["warn"]),
    ("CREATE TABLE t (n VARCHAR(10) CHARACTER SET utf8mb3)", ["warn"]),
    ("CREATE TABLE t (n VARCHAR(10)) COLLATE utf8_general_ci", ["warn"]),
    ("ALTER TABLE users ADD COLUMN seq INT NOT NULL AUTO_INCREMENT UNIQUE", ["warn"]),
    ("ALTER TABLE users CONVERT TO CHARACTER SET utf8", ["warn"]),
    ("CREATE TABLE t (id INT AUTO_INCREMENT PRIMARY KEY) CHARSET=utf8mb3", ["warn", "warn"]),
    ("CREATE TABLE t (id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY) DEFAULT CHARSET=utf8mb4", []),
    ("CREATE TABLE t (n INT, m VARCHAR(5) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci)", []),
    ("ALTER TABLE users ADD COLUMN age2 INT", []),
    ("ALTER TABLE users MODIFY id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT", []),
    ("UPDATE users SET name = 'utf8' WHERE id = 1", []),
]


@pytest.mark.parametrize("sql,expected", L10_CASES)
def test_l10(check, sql, expected):
    assert check(sql, "L10") == expected
