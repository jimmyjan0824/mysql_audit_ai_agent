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


def test_delimiter_blocks_keep_routines_whole():
    sql = (
        "ALTER TABLE a ADD COLUMN x INT;\n"
        "DELIMITER ;;\n"
        "CREATE PROCEDURE p() BEGIN\n  UPDATE a SET x = 1;\n  DELETE FROM a;\nEND;;\n"
        "DELIMITER ;\n"
        "CALL p();\n"
    )
    stmts = split_statements(sql)
    assert [s.words[0] for s in stmts] == ["ALTER", "CREATE", "CALL"]
    assert [s.line for s in stmts] == [1, 3, 8]
    assert stmts[1].sql.endswith("END")


def test_routine_body_is_not_reviewed():
    from mysql_audit import review

    sql = "DELIMITER $$\nCREATE PROCEDURE p() BEGIN DELETE FROM a; END$$\nDELIMITER ;\n"
    assert [f.rule_id for f in review(sql).findings] == []
