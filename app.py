from flask import Flask, render_template, request, url_for, redirect, Response, abort, session, g
import os
import json
import sqlite3
import secrets
import functools
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

DATA         = os.path.join(os.getcwd(), "data")
ADMIN_PASTES = os.path.join(DATA, "admin")
ANON_PASTES  = os.path.join(DATA, "other")
META_DIR     = os.path.join(DATA, "meta")
USERS_DB     = os.path.join(DATA, "users.db")
SECRET_FILE  = os.path.join(DATA, "secret_key")

if os.path.exists(SECRET_FILE):
    with open(SECRET_FILE, "r") as f:
        app.secret_key = f.read().strip()
else:
    key = secrets.token_hex(32)
    with open(SECRET_FILE, "w") as f:
        f.write(key)
    app.secret_key = key

os.makedirs(META_DIR, exist_ok=True)

RANKS = ["user", "moderator", "admin", "owner"]
RANK_COLORS = {
    "owner":     "#ff3333",
    "admin":     "#ff8800",
    "moderator": "#ffcc00",
    "user":      "#44cc44",
    "anonymous": "#666666",
}

with open(os.path.join(DATA, "template"), "r", encoding="utf-8") as f:
    _DEFAULT_POST_TEMPLATE = f.read()


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
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            rank         TEXT NOT NULL DEFAULT 'user',
            created_at   TEXT NOT NULL
        )
    """)
    db.commit()
    db.close()

init_db()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_globals():
    user = current_user()
    return dict(
        current_user=user,
        current_rank_color=RANK_COLORS.get(user["rank"] if user else "anonymous", "#666"),
        rank_colors=RANK_COLORS,
        RANKS=RANKS,
    )


def _save_meta(filename, author, rank):
    with open(os.path.join(META_DIR, filename + ".json"), "w", encoding="utf-8") as f:
        json.dump({"author": author, "rank": rank}, f)


def _load_meta(filename):
    path = os.path.join(META_DIR, filename + ".json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _file_info(path, name):
    stats = os.stat(path)
    meta  = _load_meta(name)
    return {
        "name":          name,
        "size":          round(stats.st_size / 1000, 2),
        "creation_date": datetime.utcfromtimestamp(int(stats.st_mtime)).strftime('%d-%m-%Y'),
        "creation_time": datetime.utcfromtimestamp(int(stats.st_mtime)).strftime('%H:%M:%S'),
        "author":        meta["author"] if meta else None,
        "author_rank":   meta["rank"]   if meta else None,
    }


def _load_pastes(directory):
    posts = []
    for name in sorted(os.listdir(directory),
                       key=lambda n: os.path.getmtime(os.path.join(directory, n)),
                       reverse=True):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            posts.append(_file_info(path, name))
    return posts


def _load_loosers():
    with open(os.path.join(DATA, "hol.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    return [l for l in data.get("loosers", []) if isinstance(l, dict)]


@app.route("/")
def index():
    query       = request.args.get("q", "").strip()
    admin_posts = _load_pastes(ADMIN_PASTES)
    anon_posts  = _load_pastes(ANON_PASTES)
    if query:
        q = query.lower()
        admin_posts = [p for p in admin_posts if q in p["name"].lower()]
        anon_posts  = [p for p in anon_posts  if q in p["name"].lower()]
    return render_template("index.html",
                           admin_posts_list=admin_posts,
                           anon_posts_list=anon_posts,
                           query=query)


@app.route("/new")
def new_paste():
    return render_template("new.html", paste_template_text=_DEFAULT_POST_TEMPLATE)


@app.route("/new_paste", methods=["POST"])
def new_paste_form_post():
    title   = request.form.get("pasteTitle", "").replace("/", "%2F").strip()
    content = request.form.get("pasteContent", "")
    if not title or not content:
        return "Error: title and content are required.", 400

    user     = current_user()
    is_admin = user and RANKS.index(user["rank"]) >= RANKS.index("admin")
    dest     = ADMIN_PASTES if is_admin else ANON_PASTES

    with open(os.path.join(dest, title), "w", encoding="utf-8") as f:
        f.write(content)

    author = user["username"] if user else "Anonymous"
    rank   = user["rank"]    if user else "anonymous"
    _save_meta(title, author, rank)

    if is_admin:
        return redirect(url_for("admin_post", file=title))
    return redirect(url_for("post", file=title))


@app.route("/post/<file>")
def post(file):
    path = os.path.join(ANON_PASTES, file)
    if not os.path.isfile(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    info = _file_info(path, file)
    user = current_user()
    meta = _load_meta(file)
    can_delete = bool(
        user and (
            (meta and meta.get("author") == user["username"]) or
            RANKS.index(user["rank"]) >= RANKS.index("moderator")
        )
    )
    return render_template("post.html",
                           filename=file,
                           file_content=content,
                           creation_date=info["creation_date"],
                           creation_time=info["creation_time"],
                           size=info["size"],
                           author=info["author"],
                           author_rank=info["author_rank"],
                           can_delete=can_delete)


@app.route("/admin/<file>")
def admin_post(file):
    path = os.path.join(ADMIN_PASTES, file)
    if not os.path.isfile(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    info = _file_info(path, file)
    user = current_user()
    can_delete = bool(user and RANKS.index(user["rank"]) >= RANKS.index("admin"))
    return render_template("admin.html",
                           filename=file,
                           file_content=content,
                           creation_date=info["creation_date"],
                           creation_time=info["creation_time"],
                           size=info["size"],
                           author=info["author"],
                           author_rank=info["author_rank"],
                           can_delete=can_delete)


@app.route("/raw/post/<file>")
def raw_post(file):
    path = os.path.join(ANON_PASTES, file)
    if not os.path.isfile(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content, mimetype="text/plain")


@app.route("/raw/admin/<file>")
def raw_admin(file):
    path = os.path.join(ADMIN_PASTES, file)
    if not os.path.isfile(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content, mimetype="text/plain")


@app.route("/delete/post/<file>", methods=["POST"])
def delete_post(file):
    user = current_user()
    if not user:
        abort(403)
    path = os.path.join(ANON_PASTES, file)
    if not os.path.isfile(path):
        abort(404)
    meta      = _load_meta(file)
    is_author = meta and meta.get("author") == user["username"]
    is_mod    = RANKS.index(user["rank"]) >= RANKS.index("moderator")
    if not (is_author or is_mod):
        abort(403)
    os.remove(path)
    mp = os.path.join(META_DIR, file + ".json")
    if os.path.exists(mp):
        os.remove(mp)
    return redirect(url_for("index"))


@app.route("/delete/admin/<file>", methods=["POST"])
def delete_admin_post(file):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    path = os.path.join(ADMIN_PASTES, file)
    if not os.path.isfile(path):
        abort(404)
    os.remove(path)
    mp = os.path.join(META_DIR, file + ".json")
    if os.path.exists(mp):
        os.remove(mp)
    return redirect(url_for("index"))


@app.route("/tos")
def tos():
    with open(os.path.join(DATA, "tos"), "r", encoding="utf-8") as f:
        content = f.read()
    return render_template("tos.html", file_content=content)


@app.route("/hol")
def hall_of_loosers():
    return render_template("hol.html", loosers_list=_load_loosers())


@app.route("/links")
@app.route("/pages")
def list_of_pages():
    return render_template("pages.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user     = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "Invalid username or password."
        else:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(request.args.get("next") or url_for("index"))
    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")
        if not username or len(username) < 2:
            error = "Username must be at least 2 characters."
        elif len(username) > 24:
            error = "Username must be 24 characters or fewer."
        elif not all(c.isalnum() or c in "-_" for c in username):
            error = "Username may only contain letters, numbers, hyphens, and underscores."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            db       = get_db()
            existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                error = "Username already taken."
            else:
                db.execute(
                    "INSERT INTO users (username, password_hash, rank, created_at) VALUES (?, ?, ?, ?)",
                    (username, generate_password_hash(password), "user",
                     datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
                )
                db.commit()
                user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("index"))
    return render_template("register.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/user/<username>")
def user_profile(username):
    db   = get_db()
    prof = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not prof:
        abort(404)
    admin_pastes, anon_pastes = [], []
    for name in os.listdir(ADMIN_PASTES):
        path = os.path.join(ADMIN_PASTES, name)
        if os.path.isfile(path):
            meta = _load_meta(name)
            if meta and meta.get("author", "").lower() == username.lower():
                admin_pastes.append(_file_info(path, name))
    for name in os.listdir(ANON_PASTES):
        path = os.path.join(ANON_PASTES, name)
        if os.path.isfile(path):
            meta = _load_meta(name)
            if meta and meta.get("author", "").lower() == username.lower():
                anon_pastes.append(_file_info(path, name))
    admin_pastes.sort(key=lambda p: p["creation_date"], reverse=True)
    anon_pastes.sort(key=lambda p: p["creation_date"], reverse=True)
    return render_template("profile.html",
                           profile_user=prof,
                           admin_pastes=admin_pastes,
                           anon_pastes=anon_pastes)


@app.route("/manage-users")
def manage_users():
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    users = get_db().execute(
        "SELECT * FROM users ORDER BY CASE rank "
        "WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 "
        "WHEN 'moderator' THEN 2 ELSE 3 END, username ASC"
    ).fetchall()
    return render_template("manage_users.html", users=users)


@app.route("/manage-users/<username>/rank", methods=["POST"])
def update_user_rank(username):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    new_rank = request.form.get("rank", "user")
    if new_rank not in RANKS:
        abort(400)
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not target:
        abort(404)
    if user["rank"] != "owner":
        if RANKS.index(new_rank) >= RANKS.index(user["rank"]):
            abort(403)
        if RANKS.index(target["rank"]) >= RANKS.index(user["rank"]):
            abort(403)
    db.execute("UPDATE users SET rank = ? WHERE username = ?", (new_rank, username))
    db.commit()
    return redirect(url_for("manage_users"))


@app.route("/manage-users/<username>/delete", methods=["POST"])
def delete_user(username):
    user = current_user()
    if not user or user["rank"] != "owner":
        abort(403)
    get_db().execute("DELETE FROM users WHERE username = ?", (username,))
    get_db().commit()
    return redirect(url_for("manage_users"))


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template("404.html"), 403


if __name__ == "__main__":
    app.run("0.0.0.0", port=5000, debug=False)
