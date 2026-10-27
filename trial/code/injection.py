# expect: block
# rules: L12
# User input pasted into SQL: SQL injection.
def find_user(cur, email):
    cur.execute(f"SELECT id, name FROM users WHERE email = '{email}'")
    return cur.fetchone()
