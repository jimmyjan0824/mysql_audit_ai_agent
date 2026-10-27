import pytest

from mysql_audit import review

SAFE_PREFIX = "SET SESSION lock_wait_timeout = 5;\n"

SCHEMA = """
CREATE TABLE users (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(50) NOT NULL,
  email VARCHAR(60) NOT NULL,
  code VARCHAR(200) CHARACTER SET latin1,
  status ENUM('active', 'disabled') NOT NULL,
  age INT
) DEFAULT CHARSET=utf8mb4;
CREATE TABLE legacy (title VARCHAR(80)) DEFAULT CHARSET=utf8mb3;
"""


def hits(sql, rule_id, schema=SCHEMA):
    """Severities of the findings of one rule."""
    return [f.severity.value for f in review(sql, schema=schema).findings if f.rule_id == rule_id]


@pytest.fixture
def check():
    return hits
