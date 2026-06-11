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

RANKS = ["user", "vip", "crim", "rich", "moderator", "admin", "owner"]
STAFF_RANKS  = {"moderator", "admin", "owner"}
DONOR_RANKS  = {"vip", "crim", "rich"}

RANK_COLORS = {
    "owner":     "#ff3333",
    "admin":     "#ff8800",
    "moderator": "#ffcc00",
    "rich":      "#00cc77",
    "crim":      "#cc2244",
    "vip":       "#aa44ff",
    "user":      "#44cc44",
    "anonymous": "#666666",
}
RANK_INFO = {
    "owner": {
        "desc": "Site owner with unrestricted control over all content and accounts.",
        "perms": ["All admin permissions", "Delete any user account", "Promote users to any rank"],
        "price": None,
    },
    "admin": {
        "desc": "Trusted administrator responsible for site management and moderation.",
        "perms": ["All moderator permissions", "Create admin pastes", "Delete any admin paste", "Manage user ranks (below admin)"],
        "price": None,
    },
    "moderator": {
        "desc": "Community moderator who keeps anonymous content clean.",
        "perms": ["All user permissions", "Delete any anonymous paste"],
        "price": None,
    },
    "rich": {
        "desc": "The highest donor tier. Flash your wealth with an exclusive green name.",
        "perms": ["Exclusive name color", "Rich badge", "Priority support"],
        "price": "$25",
    },
    "crim": {
        "desc": "The criminal tier. Stand out with a sharp crimson name.",
        "perms": ["Exclusive name color", "Crim badge", "Forum bragging rights"],
        "price": "$10",
    },
    "vip": {
        "desc": "The entry donor tier. Show your support with a purple name.",
        "perms": ["Exclusive name color", "VIP badge"],
        "price": "$5",
    },
    "user": {
        "desc": "Standard registered member.",
        "perms": ["Create anonymous pastes", "Delete own pastes"],
        "price": "Free",
    },
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
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            rank          TEXT NOT NULL DEFAULT 'user',
            created_at    TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS store_requests (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT NOT NULL,
            rank       TEXT NOT NULL,
            note       TEXT,
            status     TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            paste_id   TEXT NOT NULL,
            paste_type TEXT NOT NULL,
            username   TEXT NOT NULL,
            content    TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            content    TEXT NOT NULL,
            author     TEXT NOT NULL,
            pinned     INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            paste_id   TEXT NOT NULL,
            paste_type TEXT NOT NULL,
            reporter   TEXT NOT NULL,
            reason     TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            paste_id   TEXT NOT NULL,
            paste_type TEXT NOT NULL,
            username   TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(paste_id, paste_type, username)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user  TEXT NOT NULL,
            to_user    TEXT NOT NULL,
            content    TEXT NOT NULL,
            read       INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS views (
            paste_id   TEXT NOT NULL,
            paste_type TEXT NOT NULL,
            count      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (paste_id, paste_type)
        )
    """)
    for col, definition in [("bio", "TEXT NOT NULL DEFAULT ''"),
                             ("profile_color", "TEXT NOT NULL DEFAULT '#666666'"),
                             ("banned", "INTEGER NOT NULL DEFAULT 0"),
                             ("ban_reason", "TEXT NOT NULL DEFAULT ''")]:
        try:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
        except Exception:
            pass
    db.commit()
    db.close()

init_db()


def _send_discord_webhook(content):
    webhook_file = os.path.join(DATA, "discord_webhook.txt")
    if not os.path.exists(webhook_file):
        return
    try:
        import urllib.request
        with open(webhook_file, "r") as _f:
            url = _f.read().strip()
        if not url:
            return
        data = json.dumps({"content": content[:2000]}).encode("utf-8")
        req  = urllib.request.Request(url, data=data,
                                      headers={"Content-Type": "application/json"},
                                      method="POST")
        urllib.request.urlopen(req, timeout=4)
    except Exception:
        pass


def _increment_view(paste_id, paste_type):
    db = get_db()
    existing = db.execute("SELECT count FROM views WHERE paste_id=? AND paste_type=?",
                          (paste_id, paste_type)).fetchone()
    if existing:
        db.execute("UPDATE views SET count=count+1 WHERE paste_id=? AND paste_type=?",
                   (paste_id, paste_type))
        count = existing["count"] + 1
    else:
        db.execute("INSERT INTO views (paste_id, paste_type, count) VALUES (?,?,1)",
                   (paste_id, paste_type))
        count = 1
    db.commit()
    return count


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
    unread_messages = 0
    if user:
        try:
            unread_messages = get_db().execute(
                "SELECT COUNT(*) FROM messages WHERE to_user=? AND read=0",
                (user["username"],)
            ).fetchone()[0]
        except Exception:
            pass
    return dict(
        current_user=user,
        current_rank_color=RANK_COLORS.get(user["rank"] if user else "anonymous", "#666"),
        rank_colors=RANK_COLORS,
        rank_info=RANK_INFO,
        RANKS=RANKS,
        STAFF_RANKS=STAFF_RANKS,
        DONOR_RANKS=DONOR_RANKS,
        unread_messages=unread_messages,
    )


def _save_meta(filename, author, rank, visibility="public", tags=""):
    with open(os.path.join(META_DIR, filename + ".json"), "w", encoding="utf-8") as f:
        json.dump({"author": author, "rank": rank, "visibility": visibility, "tags": tags}, f)


def _count_pastes_by_user():
    counts = {}
    for fname in os.listdir(META_DIR):
        if not fname.endswith(".json"):
            continue
        meta = _load_meta(fname[:-5])
        if meta and meta.get("author"):
            author = meta["author"]
            counts[author] = counts.get(author, 0) + 1
    return counts


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
        "author":        meta["author"]                          if meta else None,
        "author_rank":   meta["rank"]                            if meta else None,
        "visibility":    meta.get("visibility", "public")        if meta else "public",
        "tags":          meta.get("tags", "")                    if meta else "",
    }


def _load_pastes(directory, viewer=None):
    posts = []
    viewer_name = viewer["username"] if viewer else None
    viewer_is_mod = viewer and RANKS.index(viewer["rank"]) >= RANKS.index("moderator")
    for name in sorted(os.listdir(directory),
                       key=lambda n: os.path.getmtime(os.path.join(directory, n)),
                       reverse=True):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        info = _file_info(path, name)
        vis  = info["visibility"]
        if vis == "private":
            if not (viewer_is_mod or info["author"] == viewer_name):
                continue
        elif vis == "unlisted":
            continue
        posts.append(info)
    return posts


def _load_loosers():
    with open(os.path.join(DATA, "hol.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    return [l for l in data.get("loosers", []) if isinstance(l, dict)]


@app.route("/")
def index():
    viewer        = current_user()
    query         = request.args.get("q", "").strip()
    author_filter = request.args.get("author", "").strip().lower()
    tag_filter    = request.args.get("tag", "").strip().lower()
    admin_posts   = _load_pastes(ADMIN_PASTES, viewer=viewer)
    anon_posts    = _load_pastes(ANON_PASTES,  viewer=viewer)
    if query:
        q = query.lower()
        admin_posts = [p for p in admin_posts if q in p["name"].lower()]
        anon_posts  = [p for p in anon_posts  if q in p["name"].lower()]
    if author_filter:
        admin_posts = [p for p in admin_posts if p["author"] and p["author"].lower() == author_filter]
        anon_posts  = [p for p in anon_posts  if p["author"] and p["author"].lower() == author_filter]
    if tag_filter:
        def _has_tag(p, t):
            return t in [x.strip().lower() for x in p["tags"].split(",") if x.strip()]
        admin_posts = [p for p in admin_posts if _has_tag(p, tag_filter)]
        anon_posts  = [p for p in anon_posts  if _has_tag(p, tag_filter)]
    pinned_anns = get_db().execute(
        "SELECT * FROM announcements WHERE pinned=1 ORDER BY created_at DESC LIMIT 3"
    ).fetchall()
    active_filter = author_filter or tag_filter
    return render_template("index.html",
                           admin_posts_list=admin_posts,
                           anon_posts_list=anon_posts,
                           query=query,
                           author_filter=author_filter,
                           tag_filter=tag_filter,
                           active_filter=active_filter,
                           pinned_announcements=pinned_anns)


@app.route("/new")
def new_paste():
    return render_template("new.html", paste_template_text=_DEFAULT_POST_TEMPLATE)


@app.route("/new_paste", methods=["POST"])
def new_paste_form_post():
    title      = request.form.get("pasteTitle", "").replace("/", "%2F").strip()
    content    = request.form.get("pasteContent", "")
    visibility = request.form.get("visibility", "public")
    raw_tags   = request.form.get("tags", "").strip()[:120]
    tags       = ",".join(t.strip().lower()[:30] for t in raw_tags.split(",") if t.strip())[:120]
    if visibility not in ("public", "unlisted", "private"):
        visibility = "public"
    if not title or not content:
        return "Error: title and content are required.", 400

    user     = current_user()
    is_admin = user and RANKS.index(user["rank"]) >= RANKS.index("admin")
    dest     = ADMIN_PASTES if is_admin else ANON_PASTES

    with open(os.path.join(dest, title), "w", encoding="utf-8") as f:
        f.write(content)

    author = user["username"] if user else "Anonymous"
    rank   = user["rank"]    if user else "anonymous"
    _save_meta(title, author, rank, visibility, tags)

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
    vis  = info["visibility"]
    is_mod = user and RANKS.index(user["rank"]) >= RANKS.index("moderator")
    is_author = user and info["author"] == user["username"]
    if vis == "private" and not (is_mod or is_author):
        abort(403)
    meta = _load_meta(file)
    can_delete = bool(user and (is_author or is_mod))
    can_report = bool(user and not is_author)
    comments = get_db().execute(
        "SELECT * FROM comments WHERE paste_id=? AND paste_type='post' ORDER BY created_at ASC",
        (file,)
    ).fetchall()
    already_reported = bool(user and get_db().execute(
        "SELECT id FROM reports WHERE paste_id=? AND paste_type='post' AND reporter=? AND status='open'",
        (file, user["username"])
    ).fetchone())
    view_count  = _increment_view(file, "post")
    likes_count = get_db().execute("SELECT COUNT(*) FROM likes WHERE paste_id=? AND paste_type='post'", (file,)).fetchone()[0]
    user_liked  = bool(user and get_db().execute(
        "SELECT id FROM likes WHERE paste_id=? AND paste_type='post' AND username=?", (file, user["username"])
    ).fetchone())
    return render_template("post.html",
                           filename=file,
                           file_content=content,
                           creation_date=info["creation_date"],
                           creation_time=info["creation_time"],
                           size=info["size"],
                           author=info["author"],
                           author_rank=info["author_rank"],
                           visibility=vis,
                           tags=info["tags"],
                           can_delete=can_delete,
                           can_report=can_report,
                           already_reported=already_reported,
                           comments=comments,
                           view_count=view_count,
                           likes_count=likes_count,
                           user_liked=user_liked)


@app.route("/admin/<file>")
def admin_post(file):
    path = os.path.join(ADMIN_PASTES, file)
    if not os.path.isfile(path):
        abort(404)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    info = _file_info(path, file)
    user = current_user()
    is_admin  = user and RANKS.index(user["rank"]) >= RANKS.index("admin")
    is_author = user and info["author"] == user["username"]
    can_delete = bool(is_admin)
    can_report = bool(user and not is_author and not is_admin)
    comments = get_db().execute(
        "SELECT * FROM comments WHERE paste_id=? AND paste_type='admin' ORDER BY created_at ASC",
        (file,)
    ).fetchall()
    already_reported = bool(user and get_db().execute(
        "SELECT id FROM reports WHERE paste_id=? AND paste_type='admin' AND reporter=? AND status='open'",
        (file, user["username"])
    ).fetchone())
    view_count  = _increment_view(file, "admin")
    likes_count = get_db().execute("SELECT COUNT(*) FROM likes WHERE paste_id=? AND paste_type='admin'", (file,)).fetchone()[0]
    user_liked  = bool(user and get_db().execute(
        "SELECT id FROM likes WHERE paste_id=? AND paste_type='admin' AND username=?", (file, user["username"])
    ).fetchone())
    return render_template("admin.html",
                           filename=file,
                           file_content=content,
                           creation_date=info["creation_date"],
                           creation_time=info["creation_time"],
                           size=info["size"],
                           author=info["author"],
                           author_rank=info["author_rank"],
                           visibility=info["visibility"],
                           tags=info["tags"],
                           can_delete=can_delete,
                           can_report=can_report,
                           already_reported=already_reported,
                           comments=comments,
                           view_count=view_count,
                           likes_count=likes_count,
                           user_liked=user_liked)


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
        elif user["banned"]:
            reason = user["ban_reason"]
            error = f"Your account has been suspended.{(' Reason: ' + reason) if reason else ''}"
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
                _send_discord_webhook(f"👤 **New registration** — **{username}** joined Crossbin.")
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
    all_paste_names = [p["name"] for p in admin_pastes] + [p["name"] for p in anon_pastes]
    total_views = 0
    if all_paste_names:
        placeholders = ",".join("?" * len(all_paste_names))
        rows = db.execute(
            f"SELECT SUM(count) FROM views WHERE paste_id IN ({placeholders})",
            all_paste_names
        ).fetchone()
        total_views = rows[0] or 0
    return render_template("profile.html",
                           profile_user=prof,
                           admin_pastes=admin_pastes,
                           anon_pastes=anon_pastes,
                           total_views=total_views)


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


@app.route("/store", methods=["GET", "POST"])
def store():
    user = current_user()
    error = success = None
    if request.method == "POST":
        if not user:
            return redirect(url_for("login", next="/store"))
        rank = request.form.get("rank", "").strip()
        note = request.form.get("note", "").strip()[:300]
        if rank not in DONOR_RANKS:
            error = "Invalid rank selection."
        else:
            existing = get_db().execute(
                "SELECT id FROM store_requests WHERE username = ? AND rank = ? AND status = 'pending'",
                (user["username"], rank)
            ).fetchone()
            if existing:
                error = "You already have a pending request for that rank."
            else:
                get_db().execute(
                    "INSERT INTO store_requests (username, rank, note, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                    (user["username"], rank, note, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
                )
                get_db().commit()
                success = f"Request for {rank} submitted! An admin will review it shortly."
    return render_template("store.html", error=error, success=success)


@app.route("/store/requests")
def store_requests():
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    requests_list = get_db().execute(
        "SELECT * FROM store_requests ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC"
    ).fetchall()
    return render_template("store_requests.html", requests_list=requests_list)


@app.route("/store/requests/<int:req_id>/approve", methods=["POST"])
def approve_request(req_id):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    db  = get_db()
    req = db.execute("SELECT * FROM store_requests WHERE id = ?", (req_id,)).fetchone()
    if not req:
        abort(404)
    db.execute("UPDATE store_requests SET status = 'approved' WHERE id = ?", (req_id,))
    db.execute("UPDATE users SET rank = ? WHERE username = ?", (req["rank"], req["username"]))
    db.commit()
    return redirect(url_for("store_requests"))


@app.route("/store/requests/<int:req_id>/deny", methods=["POST"])
def deny_request(req_id):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    db = get_db()
    if not db.execute("SELECT id FROM store_requests WHERE id = ?", (req_id,)).fetchone():
        abort(404)
    db.execute("UPDATE store_requests SET status = 'denied' WHERE id = ?", (req_id,))
    db.commit()
    return redirect(url_for("store_requests"))


@app.route("/users")
def user_list():
    users = get_db().execute(
        "SELECT * FROM users ORDER BY CASE rank "
        "WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'moderator' THEN 2 "
        "WHEN 'rich' THEN 3 WHEN 'crim' THEN 4 WHEN 'vip' THEN 5 "
        "ELSE 6 END, username ASC"
    ).fetchall()
    paste_counts = _count_pastes_by_user()
    return render_template("users.html", users=users, paste_counts=paste_counts)


@app.route("/staff")
def staff_list():
    staff = get_db().execute(
        "SELECT * FROM users WHERE rank IN ('owner','admin','moderator') "
        "ORDER BY CASE rank "
        "WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 "
        "WHEN 'moderator' THEN 2 END, username ASC"
    ).fetchall()
    grouped = {}
    for rank in ["owner", "admin", "moderator"]:
        grouped[rank] = [u for u in staff if u["rank"] == rank]
    return render_template("staff.html", grouped=grouped)


@app.route("/ranks")
def ranks_page():
    return render_template("ranks.html")


# ── Comments ──────────────────────────────────────────────────────────────────
@app.route("/comment/<paste_type>/<file>", methods=["POST"])
@login_required
def add_comment(paste_type, file):
    if paste_type not in ("post", "admin"):
        abort(404)
    user    = current_user()
    content = request.form.get("content", "").strip()[:1000]
    if content:
        get_db().execute(
            "INSERT INTO comments (paste_id, paste_type, username, content, created_at) VALUES (?,?,?,?,?)",
            (file, paste_type, user["username"], content, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
        )
        get_db().commit()
    target = url_for("post", file=file) if paste_type == "post" else url_for("admin_post", file=file)
    return redirect(target + "#comments")


@app.route("/delete-comment/<int:cid>", methods=["POST"])
@login_required
def delete_comment(cid):
    user    = current_user()
    db      = get_db()
    comment = db.execute("SELECT * FROM comments WHERE id = ?", (cid,)).fetchone()
    if not comment:
        abort(404)
    is_author = comment["username"] == user["username"]
    is_mod    = RANKS.index(user["rank"]) >= RANKS.index("moderator")
    if not (is_author or is_mod):
        abort(403)
    db.execute("DELETE FROM comments WHERE id = ?", (cid,))
    db.commit()
    target = url_for("post", file=comment["paste_id"]) if comment["paste_type"] == "post" else url_for("admin_post", file=comment["paste_id"])
    return redirect(target + "#comments")


# ── Announcements ─────────────────────────────────────────────────────────────
@app.route("/announcements")
def announcements():
    anns = get_db().execute(
        "SELECT * FROM announcements ORDER BY pinned DESC, created_at DESC"
    ).fetchall()
    return render_template("announcements.html", announcements=anns)


@app.route("/announcements/new", methods=["GET", "POST"])
def new_announcement():
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    error = None
    if request.method == "POST":
        title   = request.form.get("title", "").strip()[:100]
        content = request.form.get("content", "").strip()[:2000]
        pinned  = 1 if request.form.get("pinned") else 0
        if not title or not content:
            error = "Title and content are required."
        else:
            get_db().execute(
                "INSERT INTO announcements (title, content, author, pinned, created_at) VALUES (?,?,?,?,?)",
                (title, content, user["username"], pinned, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            )
            get_db().commit()
            return redirect(url_for("announcements"))
    return render_template("new_announcement.html", error=error)


@app.route("/announcements/<int:ann_id>/delete", methods=["POST"])
def delete_announcement(ann_id):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    get_db().execute("DELETE FROM announcements WHERE id = ?", (ann_id,))
    get_db().commit()
    return redirect(url_for("announcements"))


@app.route("/announcements/<int:ann_id>/toggle-pin", methods=["POST"])
def toggle_pin(ann_id):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    ann = get_db().execute("SELECT * FROM announcements WHERE id = ?", (ann_id,)).fetchone()
    if not ann:
        abort(404)
    get_db().execute("UPDATE announcements SET pinned = ? WHERE id = ?", (0 if ann["pinned"] else 1, ann_id))
    get_db().commit()
    return redirect(url_for("announcements"))


# ── Admin Dashboard ───────────────────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    db = get_db()
    stats = {
        "total_users":    db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "total_comments": db.execute("SELECT COUNT(*) FROM comments").fetchone()[0],
        "pending_store":  db.execute("SELECT COUNT(*) FROM store_requests WHERE status='pending'").fetchone()[0],
        "open_reports":   db.execute("SELECT COUNT(*) FROM reports WHERE status='open'").fetchone()[0],
        "announcements":  db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0],
        "admin_pastes":   len([f for f in os.listdir(ADMIN_PASTES) if os.path.isfile(os.path.join(ADMIN_PASTES, f))]),
        "anon_pastes":    len([f for f in os.listdir(ANON_PASTES)  if os.path.isfile(os.path.join(ANON_PASTES, f)) and not f.startswith(".")]),
    }
    recent_users   = db.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 10").fetchall()
    recent_reports = db.execute("SELECT * FROM reports WHERE status='open' ORDER BY created_at DESC LIMIT 5").fetchall()
    return render_template("dashboard.html", stats=stats, recent_users=recent_users, recent_reports=recent_reports)


# ── User Settings ─────────────────────────────────────────────────────────────
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()
    error = success = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "change_password":
            current_pw = request.form.get("current_password", "")
            new_pw     = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if not check_password_hash(user["password_hash"], current_pw):
                error = "Current password is incorrect."
            elif len(new_pw) < 6:
                error = "New password must be at least 6 characters."
            elif new_pw != confirm_pw:
                error = "Passwords do not match."
            else:
                get_db().execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new_pw), user["id"])
                )
                get_db().commit()
                success = "Password changed successfully."
        elif action == "update_profile":
            bio   = request.form.get("bio", "").strip()[:300]
            color = request.form.get("profile_color", "#666666").strip()
            if not color.startswith("#") or len(color) not in (4, 7):
                color = "#666666"
            get_db().execute(
                "UPDATE users SET bio=?, profile_color=? WHERE id=?",
                (bio, color, user["id"])
            )
            get_db().commit()
            success = "Profile updated."
    user = current_user()
    return render_template("settings.html", error=error, success=success)


# ── Reports ───────────────────────────────────────────────────────────────────
@app.route("/report/<paste_type>/<file>", methods=["POST"])
@login_required
def report_paste(paste_type, file):
    if paste_type not in ("post", "admin"):
        abort(404)
    user   = current_user()
    reason = request.form.get("reason", "").strip()[:500]
    if reason:
        existing = get_db().execute(
            "SELECT id FROM reports WHERE paste_id=? AND paste_type=? AND reporter=? AND status='open'",
            (file, paste_type, user["username"])
        ).fetchone()
        if not existing:
            get_db().execute(
                "INSERT INTO reports (paste_id, paste_type, reporter, reason, status, created_at) VALUES (?,?,?,?,'open',?)",
                (file, paste_type, user["username"], reason, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            )
            get_db().commit()
            _send_discord_webhook(
                f"🚨 **New Report** — `{paste_type}/{file}`\n"
                f"Reporter: **{user['username']}**\nReason: {reason}"
            )
    target = url_for("post", file=file) if paste_type == "post" else url_for("admin_post", file=file)
    return redirect(target)


@app.route("/reports")
def reports():
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("moderator"):
        abort(403)
    reports_list = get_db().execute(
        "SELECT * FROM reports ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, created_at DESC"
    ).fetchall()
    return render_template("reports.html", reports_list=reports_list)


@app.route("/reports/<int:rid>/resolve", methods=["POST"])
def resolve_report(rid):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("moderator"):
        abort(403)
    get_db().execute("UPDATE reports SET status='resolved' WHERE id=?", (rid,))
    get_db().commit()
    return redirect(url_for("reports"))


# ── Likes ─────────────────────────────────────────────────────────────────────
@app.route("/like/<paste_type>/<file>", methods=["POST"])
@login_required
def toggle_like(paste_type, file):
    if paste_type not in ("post", "admin"):
        abort(404)
    user = current_user()
    db   = get_db()
    if db.execute("SELECT id FROM likes WHERE paste_id=? AND paste_type=? AND username=?",
                  (file, paste_type, user["username"])).fetchone():
        db.execute("DELETE FROM likes WHERE paste_id=? AND paste_type=? AND username=?",
                   (file, paste_type, user["username"]))
    else:
        db.execute("INSERT OR IGNORE INTO likes (paste_id, paste_type, username, created_at) VALUES (?,?,?,?)",
                   (file, paste_type, user["username"], datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    target = url_for("post", file=file) if paste_type == "post" else url_for("admin_post", file=file)
    return redirect(target)


# ── Messages ──────────────────────────────────────────────────────────────────
@app.route("/messages")
@login_required
def messages():
    me = current_user()["username"]
    db = get_db()
    rows = db.execute("""
        SELECT CASE WHEN from_user=? THEN to_user ELSE from_user END as other_user,
               MAX(created_at) as last_at,
               SUM(CASE WHEN to_user=? AND read=0 THEN 1 ELSE 0 END) as unread
        FROM messages
        WHERE from_user=? OR to_user=?
        GROUP BY other_user
        ORDER BY last_at DESC
    """, (me, me, me, me)).fetchall()
    convos = []
    for row in rows:
        last_msg   = db.execute(
            "SELECT content FROM messages WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?) ORDER BY created_at DESC LIMIT 1",
            (me, row["other_user"], row["other_user"], me)
        ).fetchone()
        other_info = db.execute("SELECT rank FROM users WHERE username=?", (row["other_user"],)).fetchone()
        convos.append({
            "other_user":   row["other_user"],
            "other_rank":   other_info["rank"] if other_info else "user",
            "last_at":      row["last_at"],
            "unread":       row["unread"],
            "last_preview": last_msg["content"] if last_msg else "",
        })
    return render_template("messages.html", convos=convos)


@app.route("/messages/<username>", methods=["GET", "POST"])
@login_required
def conversation(username):
    me = current_user()
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not target or target["username"].lower() == me["username"].lower():
        abort(404)
    if request.method == "POST":
        content = request.form.get("content", "").strip()[:2000]
        if content:
            db.execute(
                "INSERT INTO messages (from_user, to_user, content, read, created_at) VALUES (?,?,?,0,?)",
                (me["username"], target["username"], content, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
            )
            db.commit()
        return redirect(url_for("conversation", username=target["username"]) + "#bottom")
    db.execute("UPDATE messages SET read=1 WHERE from_user=? AND to_user=? AND read=0",
               (target["username"], me["username"]))
    db.commit()
    thread = db.execute("""
        SELECT * FROM messages
        WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
        ORDER BY created_at ASC
    """, (me["username"], target["username"], target["username"], me["username"])).fetchall()
    return render_template("conversation.html", target=target, thread=thread)


@app.route("/messages/<int:mid>/delete", methods=["POST"])
@login_required
def delete_message(mid):
    me  = current_user()
    db  = get_db()
    msg = db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    if not msg:
        abort(404)
    if msg["from_user"] != me["username"] and RANKS.index(me["rank"]) < RANKS.index("moderator"):
        abort(403)
    other = msg["to_user"] if msg["from_user"] == me["username"] else msg["from_user"]
    db.execute("DELETE FROM messages WHERE id=?", (mid,))
    db.commit()
    return redirect(url_for("conversation", username=other) + "#bottom")


# ── Ban System ────────────────────────────────────────────────────────────────
@app.route("/ban/<username>", methods=["POST"])
def ban_user(username):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("moderator"):
        abort(403)
    reason = request.form.get("reason", "").strip()[:200]
    db     = get_db()
    target = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not target:
        abort(404)
    if RANKS.index(target["rank"]) >= RANKS.index(user["rank"]):
        abort(403)
    db.execute("UPDATE users SET banned=1, ban_reason=? WHERE username=?", (reason, username))
    db.commit()
    return redirect(url_for("manage_users"))


@app.route("/unban/<username>", methods=["POST"])
def unban_user(username):
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("moderator"):
        abort(403)
    get_db().execute("UPDATE users SET banned=0, ban_reason='' WHERE username=?", (username,))
    get_db().commit()
    return redirect(url_for("manage_users"))


# ── Site Settings (admin) ─────────────────────────────────────────────────────
@app.route("/admin-settings", methods=["GET", "POST"])
def admin_site_settings():
    user = current_user()
    if not user or RANKS.index(user["rank"]) < RANKS.index("admin"):
        abort(403)
    webhook_file = os.path.join(DATA, "discord_webhook.txt")
    webhook_url  = ""
    if os.path.exists(webhook_file):
        with open(webhook_file, "r") as f:
            webhook_url = f.read().strip()
    success = None
    if request.method == "POST":
        url = request.form.get("webhook_url", "").strip()
        with open(webhook_file, "w") as f:
            f.write(url)
        webhook_url = url
        success = "Settings saved."
    return render_template("admin_settings.html", webhook_url=webhook_url, success=success, error=None)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template("404.html"), 403


if __name__ == "__main__":
    app.run("0.0.0.0", port=5000, debug=False)
