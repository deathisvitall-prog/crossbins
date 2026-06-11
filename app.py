from flask import Flask, render_template, request, redirect, session, g, abort, Response, url_for
import os, secrets, functools
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
DATABASE_URL = os.environ["DATABASE_URL"]

# ─────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        db.close()

def exec_sql(query, args=(), fetch=False):
    cur = get_db().cursor()
    cur.execute(query, args)
    if fetch:
        return cur.fetchall()
    get_db().commit()

# ─────────────────────────────────────────────
# INIT TABLES
# ─────────────────────────────────────────────
def init_db():
    db = psycopg2.connect(DATABASE_URL)
    cur = db.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        password_hash TEXT,
        rank TEXT DEFAULT 'user',
        created_at TEXT,
        banned INTEGER DEFAULT 0,
        ban_reason TEXT DEFAULT ''
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS pastes (
        id SERIAL PRIMARY KEY,
        filename TEXT,
        content TEXT,
        author TEXT,
        created_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id SERIAL PRIMARY KEY,
        paste_id TEXT,
        username TEXT,
        content TEXT,
        created_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        id SERIAL PRIMARY KEY,
        paste_id TEXT,
        username TEXT,
        created_at TEXT,
        UNIQUE(paste_id, username)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id SERIAL PRIMARY KEY,
        paste_id TEXT,
        reporter TEXT,
        reason TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        from_user TEXT,
        to_user TEXT,
        content TEXT,
        read INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id SERIAL PRIMARY KEY,
        title TEXT,
        content TEXT,
        author TEXT,
        pinned INTEGER DEFAULT 0,
        created_at TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS store_requests (
        id SERIAL PRIMARY KEY,
        username TEXT,
        rank TEXT,
        note TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )""")

    db.commit()
    cur.close()
    db.close()

init_db()

# ─────────────────────────────────────────────
# ADMIN SEED
# ─────────────────────────────────────────────
def create_admin():
    db = psycopg2.connect(DATABASE_URL)
    cur = db.cursor()

    cur.execute("SELECT id FROM users WHERE username='admin'")
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO users (username, password_hash, rank, created_at)
            VALUES (%s,%s,'owner',%s)
        """, (
            "admin",
            generate_password_hash("123456"),
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        ))
        db.commit()

    cur.close()
    db.close()

create_admin()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    cur = get_db().cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    return cur.fetchone()

def login_required(f):
    @functools.wraps(f)
    def wrap(*a, **k):
        if not session.get("user_id"):
            return redirect("/login")
        return f(*a, **k)
    return wrap

def rank_ok(user, required):
    ranks = ["user","moderator","admin","owner"]
    return ranks.index(user["rank"]) >= ranks.index(required)

# ─────────────────────────────────────────────
# INDEX
# ─────────────────────────────────────────────
@app.route("/")
def index():
    pastes = exec_sql("SELECT * FROM pastes ORDER BY id DESC", fetch=True)
    return render_template("index.html", pastes=pastes)

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        db = get_db()
        cur = db.cursor()

        cur.execute("SELECT id FROM users WHERE username=%s", (u,))
        if cur.fetchone():
            return "Taken"

        cur.execute("""
            INSERT INTO users (username,password_hash,rank,created_at)
            VALUES (%s,%s,'user',%s)
        """, (u, generate_password_hash(p), datetime.utcnow()))

        db.commit()
        return redirect("/login")

    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        cur = get_db().cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (u,))
        user = cur.fetchone()

        if not user or not check_password_hash(user["password_hash"], p):
            return "Invalid"

        if user["banned"]:
            return "Banned"

        session["user_id"] = user["id"]
        return redirect("/")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ─────────────────────────────────────────────
# PASTES
# ─────────────────────────────────────────────
@app.route("/paste", methods=["POST"])
def paste():
    user = current_user()
    content = request.form["content"]
    file = secrets.token_hex(8)

    exec_sql("""
        INSERT INTO pastes (filename,content,author,created_at)
        VALUES (%s,%s,%s,%s)
    """, (
        file,
        content,
        user["username"] if user else "anon",
        datetime.utcnow()
    ))

    return redirect("/p/" + file)

@app.route("/p/<file>")
def view(file):
    row = exec_sql("SELECT * FROM pastes WHERE filename=%s", (file,), fetch=True)
    if not row:
        abort(404)
    return Response(row[0]["content"], mimetype="text/plain")

# ─────────────────────────────────────────────
# COMMENTS
# ─────────────────────────────────────────────
@app.route("/comment/<file>", methods=["POST"])
@login_required
def comment(file):
    user = current_user()
    exec_sql("""
        INSERT INTO comments VALUES (DEFAULT,%s,%s,%s,%s)
    """, (file, user["username"], request.form["content"], datetime.utcnow()))
    return redirect("/p/" + file)

# ─────────────────────────────────────────────
# LIKES
# ─────────────────────────────────────────────
@app.route("/like/<file>")
@login_required
def like(file):
    user = current_user()

    cur = get_db().cursor()
    cur.execute("SELECT id FROM likes WHERE paste_id=%s AND username=%s", (file,user["username"]))
    if cur.fetchone():
        exec_sql("DELETE FROM likes WHERE paste_id=%s AND username=%s", (file,user["username"]))
    else:
        exec_sql("INSERT INTO likes VALUES (DEFAULT,%s,%s,%s)", (file,user["username"],datetime.utcnow()))

    return redirect("/p/" + file)

# ─────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────
@app.route("/report/<file>", methods=["POST"])
@login_required
def report(file):
    user = current_user()
    exec_sql("""
        INSERT INTO reports VALUES (DEFAULT,%s,%s,%s,'open',%s)
    """, (file,user["username"],request.form["reason"],datetime.utcnow()))
    return redirect("/p/" + file)

# ─────────────────────────────────────────────
# BAN
# ─────────────────────────────────────────────
@app.route("/ban/<user>", methods=["POST"])
def ban(user):
    me = current_user()
    if not rank_ok(me,"moderator"):
        abort(403)

    exec_sql("UPDATE users SET banned=1 WHERE username=%s", (user,))
    return redirect("/")

# ─────────────────────────────────────────────
# MESSAGES
# ─────────────────────────────────────────────
@app.route("/msg/<user>", methods=["POST"])
@login_required
def msg(user):
    me = current_user()
    exec_sql("""
        INSERT INTO messages VALUES (DEFAULT,%s,%s,%s,0,%s)
    """, (me["username"],user,request.form["content"],datetime.utcnow()))
    return redirect("/")

# ─────────────────────────────────────────────
# ANNOUNCEMENTS
# ─────────────────────────────────────────────
@app.route("/announce", methods=["POST"])
def announce():
    me = current_user()
    if not rank_ok(me,"admin"):
        abort(403)

    exec_sql("""
        INSERT INTO announcements VALUES (DEFAULT,%s,%s,%s,0,%s)
    """, (request.form["title"],request.form["content"],me["username"],datetime.utcnow()))

    return redirect("/")

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
