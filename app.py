
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session

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
