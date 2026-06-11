from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import os

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)


# -------------------------
# HOME PAGE
# -------------------------
@app.route("/")
def index():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM pastes ORDER BY id DESC")
    pastes = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("index.html", pastes=pastes)


# -------------------------
# NEW PASTE
# -------------------------
@app.route("/new", methods=["GET", "POST"])
def new_paste():
    if request.method == "POST":
        content = request.form.get("content")

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO pastes (content) VALUES (%s)",
            (content,)
        )

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for("index"))

    return render_template("new.html")


# -------------------------
# ANNOUNCEMENTS PAGE
# -------------------------
@app.route("/announcements")
def announcements():
    return render_template("announcements.html")


# -------------------------
# STAFF PAGE
# -------------------------
@app.route("/staff")
def staff_list():
    return render_template("staff.html")


# -------------------------
# USERS PAGE
# -------------------------
@app.route("/users")
def user_list():
    return render_template("users.html")


# -------------------------
# ONE-TIME DB SETUP (IMPORTANT)
# -------------------------
@app.route("/setup-db")
def setup_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pastes (
            id SERIAL PRIMARY KEY,
            content TEXT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "Database setup complete"


# -------------------------
# RUN APP
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)
