# expect: safe
# The fix: let the driver send the value separately.
def find_user(cur, email):
    cur.execute("SELECT id, name FROM users WHERE email = %s", (email,))
    return cur.fetchone()
