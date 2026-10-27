import pytest

from mysql_audit import review_code

UNSAFE = [
    'cur.execute(f"SELECT * FROM users WHERE email = \'{email}\'")',
    "q = f'DELETE FROM sessions WHERE user_id = {uid}'",
    "const rows = await db.query(`SELECT * FROM users WHERE id = ${req.params.id}`)",
    'query = "SELECT * FROM users WHERE name = \'" + name + "\'"',
    "sql = 'UPDATE users SET plan = ' + plan",
    'cur.execute("SELECT * FROM users WHERE id = %s" % user_id)',
    'cur.execute("SELECT * FROM t WHERE id = {}".format(x))',
    'q := fmt.Sprintf("SELECT * FROM users WHERE name = \'%s\'", name)',
    '$sql = "SELECT * FROM users WHERE id = $id";',
    '$sql = "DELETE FROM users WHERE id = " . $_GET["id"];',
    'String q = String.format("SELECT * FROM t WHERE a = \'%s\'", a);',
]

SAFE = [
    'cur.execute("SELECT * FROM users WHERE email = %s", (email,))',
    "await db.query('SELECT * FROM users WHERE id = ?', [id])",
    "const rows = await sql`SELECT * FROM users WHERE id = ${id}`",
    'stmt = conn.prepareStatement("SELECT * FROM t WHERE a = ?");',
    'log.info(f"Loaded {count} users")',
    "# q = f'SELECT * FROM t WHERE id = {x}'",
    'title = "Select a plan" + suffix',
    'q := fmt.Sprintf("SELECT * FROM t LIMIT %d", n)',
]


@pytest.mark.parametrize("code", UNSAFE)
def test_l12_flags(code):
    report = review_code(code)
    assert report.verdict == "block", code
    assert report.findings[0].line == 1


@pytest.mark.parametrize("code", SAFE)
def test_l12_passes(code):
    assert review_code(code).verdict == "safe", code


def test_l12_line_numbers():
    code = "import db\n\nq = f\"SELECT * FROM t WHERE id = {x}\"\n"
    assert [f.line for f in review_code(code).findings] == [3]
