from flask import Flask, render_template, request, url_for, redirect, Response, abort, session, g
import os, json, sqlite3, secrets, functools
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ─────────────────────────────────────────────
# 🔥 RENDER PERSISTENT STORAGE FIX
# ─────────────────────────────────────────────
DATA = os.environ.get("DATA_PATH", "/var/data")

ADMIN_PASTES = os.path.join(DATA, "admin")
ANON_PASTES  = os.path.join(DATA, "other")
META_DIR     = os.path.join(DATA, "meta")
USERS_DB     = os.path.join(DATA, "users.db")
SECRET_FILE  = os.path.join(DATA, "secret_key")

for d in [DATA, ADMIN_PASTES, ANON_PASTES, META_DIR]:
    os.makedirs(d, exist_ok=True)

# ─────────────────────────────────────────────
# SECRET KEY (PERSISTENT)
# ─────────────────────────────────────────────
if os.path.exists(SECRET_FILE):
    app.secret_key = open(SECRET_FILE).read().strip()
else:
    key = secrets.token_hex(32)
    open(SECRET_FILE, "w").write(key)
    app.secret_key = key

# ─────────────────────────────────────────────
# RANK SYSTEM
# ─────────────────────────────────────────────
RANKS = ["user", "moderator", "admin", "owner"]

def rank_index(r):
    return RANKS.index(r) if r in RANKS else 0

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(USERS_DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = sqlite3.connect(USERS_DB)

    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        rank TEXT DEFAULT 'user',
        created_at TEXT,
        banned INTEGER DEFAULT 0,
        ban_reason TEXT DEFAULT ''
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paste_id TEXT,
        paste_type TEXT,
        username TEXT,
        content TEXT,
        created_at TEXT
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paste_id TEXT,
        paste_type TEXT,
        reporter TEXT,
        reason TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paste_id TEXT,
        paste_type TEXT,
        username TEXT,
        created_at TEXT,
        UNIQUE(paste_id, paste_type, username)
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user TEXT,
        to_user TEXT,
        content TEXT,
        read INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        author TEXT,
        pinned INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    db.execute("""CREATE TABLE IF NOT EXISTS store_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        rank TEXT,
        note TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )""")

    db.commit()
    db.close()

init_db()

# ─────────────────────────────────────────────
# 🔥 ADMIN ACCOUNT (YOUR REQUEST)
# ─────────────────────────────────────────────
def create_admin():
    db = sqlite3.connect(USERS_DB)

    admin_user = "admin"
    admin_pass = "123456"

    if not db.execute("SELECT id FROM users WHERE username=?", (admin_user,)).fetchone():
        db.execute("""INSERT INTO users (username, password_hash, rank, created_at)
                      VALUES (?, ?, 'owner', ?)""",
                   (admin_user,
                    generate_password_hash(admin_pass),
                    datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()

    db.close()

create_admin()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def login_required(f):
    @functools.wraps(f)
    def wrap(*a, **k):
        if not session.get("user_id"):
            return redirect("/login")
        return f(*a, **k)
    return wrap

# ─────────────────────────────────────────────
# INDEX
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
            return "Taken"

        db.execute("""INSERT INTO users VALUES (NULL,?,?,?,?,0,'')""",
                   (u, generate_password_hash(p), "user",
                    datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()
        return redirect("/login")

    return render_template("register.html")


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        user = get_db().execute("SELECT * FROM users WHERE username=?", (u,)).fetchone()

        if not user or not check_password_hash(user["password_hash"], p):
            return "Invalid"

        if user["banned"]:
            return f"Banned: {user['ban_reason']}"

        session["user_id"] = user["id"]
        return redirect("/")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ─────────────────────────────────────────────
# PASTES (FIXED STORAGE)
# ─────────────────────────────────────────────
@app.route("/paste", methods=["POST"])
def paste():
    content = request.form["content"]
    file = secrets.token_hex(8) + ".txt"

    with open(os.path.join(ANON_PASTES, file), "w", encoding="utf-8") as f:
        f.write(content)

    return redirect("/p/" + file)

@app.route("/p/<file>")
def view(file):
    path = os.path.join(ANON_PASTES, file)
    if not os.path.exists(path):
        abort(404)
    return Response(open(path).read(), mimetype="text/plain")

# ─────────────────────────────────────────────
# BAN SYSTEM
# ─────────────────────────────────────────────
@app.route("/ban/<username>", methods=["POST"])
def ban(username):
    user = current_user()
    if not user or rank_index(user["rank"]) < rank_index("moderator"):
        abort(403)

    reason = request.form.get("reason","")

    get_db().execute(
        "UPDATE users SET banned=1, ban_reason=? WHERE username=?",
        (reason, username)
    )
    get_db().commit()
    return redirect("/")

# ─────────────────────────────────────────────
# COMMENTS
# ─────────────────────────────────────────────
@app.route("/comment/<file>", methods=["POST"])
@login_required
def comment(file):
    user = current_user()
    content = request.form["content"]

    get_db().execute("""INSERT INTO comments VALUES (NULL,?,?,?,?,?)""",
                     (file, "post", user["username"], content,
                      datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    get_db().commit()

    return redirect("/p/" + file)

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
