import sqlite3, json, hashlib, hmac, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pocketsmart.db")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT,
            budget REAL, inputs TEXT, result TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);""")


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def add_user(username, pw):
    salt = os.urandom(16).hex()
    try:
        with conn() as c:
            c.execute("INSERT INTO users(username,password) VALUES(?,?)", (username, f"{salt}${_hash(pw, salt)}"))
        return True
    except sqlite3.IntegrityError:
        return False


def verify_user(username, pw):
    with conn() as c:
        u = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if u:
        salt, h = u["password"].split("$")
        if hmac.compare_digest(_hash(pw, salt), h):
            return dict(u)
    return None


def save_history(uid, kind, budget, inputs, result):
    with conn() as c:
        return c.execute("INSERT INTO history(user_id,kind,budget,inputs,result) VALUES(?,?,?,?,?)",
                         (uid, kind, budget, json.dumps(inputs), json.dumps(result))).lastrowid


def list_history(uid, limit=100):
    with conn() as c:
        rows = c.execute("SELECT id,kind,budget,created FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
        return [dict(r) for r in rows]


def get_history(uid, rid):
    with conn() as c:
        r = c.execute("SELECT * FROM history WHERE id=? AND user_id=?", (rid, uid)).fetchone()
    return dict(r) if r else None
