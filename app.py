import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session, g

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-key")

DATABASE_URL = os.environ.get("DATABASE_URL")


# ------------------------
# DB CONNECTION
# ------------------------
def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL, sslmode="require")
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


# ------------------------
# INIT DATABASE (SAFE)
# ------------------------
def init_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    cur = conn.cursor()

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # PASTES (SAFE VERSION — avoids your missing column issue)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pastes (
            id SERIAL PRIMARY KEY,
            content TEXT NOT NULL,
            author TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ANNOUNCEMENTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    # ADMIN ACCOUNT
    cur.execute("SELECT * FROM users WHERE username=%s", ("admin",))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            ("admin", "123456")
        )
        conn.commit()

    conn.close()


init_db()


# ------------------------
# HOME PAGE
# ------------------------
@app.route("/", methods=["GET"])
def index():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, content, author, created_at
        FROM pastes
        ORDER BY id DESC
    """)
    pastes = cur.fetchall()

    return render_template("index.html", pastes=pastes)


# ------------------------
# NEW PASTE (FIXED ENDPOINT)
# ------------------------
@app.route("/paste/new", methods=["GET", "POST"])
def new_paste():
    if request.method == "POST":
        content = request.form.get("content")
        author = session.get("user", "anonymous")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO pastes (content, author) VALUES (%s, %s)",
            (content, author)
        )
        conn.commit()

        return redirect(url_for("index"))

    return render_template("new_paste.html")


# ------------------------
# VIEW PASTE
# ------------------------
@app.route("/paste/<int:paste_id>")
def paste(paste_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, content, author, created_at
        FROM pastes
        WHERE id=%s
    """, (paste_id,))

    paste = cur.fetchone()

    if not paste:
        return "Not found", 404

    return render_template("paste.html", paste=paste)


# ------------------------
# LOGIN
# ------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT username FROM users WHERE username=%s AND password=%s",
            (u, p)
        )

        if cur.fetchone():
            session["user"] = u
            return redirect(url_for("index"))

        return "Invalid login", 401

    return render_template("login.html")


# ------------------------
# LOGOUT
# ------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ------------------------
# ANNOUNCEMENTS (FIX FOR NAVBAR)
# ------------------------
@app.route("/announcements")
def announcements():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, content, created_at
        FROM announcements
        ORDER BY id DESC
    """)
    data = cur.fetchall()

    return render_template("announcements.html", announcements=data)


# ------------------------
# STAFF PAGE (FIX FOR NAVBAR ERROR)
# ------------------------
@app.route("/staff")
def staff_list():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, username FROM users ORDER BY id DESC")
    users = cur.fetchall()

    return render_template("staff_list.html", users=users)


# ------------------------
# RUN
# ------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
