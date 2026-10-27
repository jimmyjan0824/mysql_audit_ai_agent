from mysql_audit.splitter import split_statements


def test_semicolon_inside_string_and_comment():
    sql = "UPDATE t SET a = 'x;y' WHERE id = 1; -- note; here\nDELETE FROM t WHERE id = 2;"
    stmts = split_statements(sql)
    assert [s.sql for s in stmts] == ["UPDATE t SET a = 'x;y' WHERE id = 1", "DELETE FROM t WHERE id = 2"]


def test_line_numbers():
    stmts = split_statements("SELECT 1;\n\nSELECT 2;\nSELECT\n3")
    assert [s.line for s in stmts] == [1, 3, 4]


def test_empty_script():
    assert split_statements("  -- nothing\n") == []
