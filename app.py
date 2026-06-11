import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "change_this_key"

# -----------------------------
# DATABASE
# -----------------------------
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # USERS TABLE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT
        )
    """)

    # PASTES TABLE (safe schema fix)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pastes (
            id SERIAL PRIMARY KEY
        )
    """)

    # FIX OLD/INCOMPLETE TABLES
    cur.execute("ALTER TABLE pastes ADD COLUMN IF NOT EXISTS title TEXT")
    cur.execute("ALTER TABLE pastes ADD COLUMN IF NOT EXISTS content TEXT")
    cur.execute("ALTER TABLE pastes ADD COLUMN IF NOT EXISTS author TEXT")

    # ADMIN ACCOUNT
    cur.execute("SELECT username FROM users WHERE username=%s", ("admin",))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            ("admin", "123456")
        )

    conn.commit()
    conn.close()


try:
    init_db()
except Exception as e:
    print("DB init warning:", e)

# -----------------------------
# ROUTES
# -----------------------------

@app.route("/")
def index():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, title, author FROM pastes ORDER BY id DESC")
    pastes = cur.fetchall()

    conn.close()

    return render_template("index.html", pastes=pastes)


# FIX: missing route from your navbar error
@app.route("/new_paste")
def new_paste():
    return redirect(url_for("paste"))


@app.route("/paste", methods=["GET", "POST"])
def paste():
    if request.method == "POST":
        title = request.form.get("title")
        content = request.form.get("content")
        author = session.get("user", "guest")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO pastes (title, content, author) VALUES (%s, %s, %s)",
            (title, content, author)
        )

        conn.commit()
        conn.close()

        return redirect(url_for("index"))

    return render_template("paste.html")


@app.route("/paste/<int:pid>")
def view_paste(pid):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT title, content, author FROM pastes WHERE id=%s", (pid,))
    paste = cur.fetchone()

    conn.close()

    return render_template("view_paste.html", paste=paste)


# -----------------------------
# LOGIN
# -----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE username=%s AND password=%s", (u, p))
        user = cur.fetchone()

        conn.close()

        if user:
            session["user"] = u
            return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run()
