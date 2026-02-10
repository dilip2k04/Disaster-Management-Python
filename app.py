from flask import Flask, request, render_template, redirect, url_for, session, flash
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# =====================================================
# INIT
# =====================================================

load_dotenv()

app = Flask(__name__)
app.secret_key = "dev-secret-key"

DB_NAME = "users.db"


# =====================================================
# DATABASE
# =====================================================

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        c = conn.cursor()

        # USERS
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE COLLATE NOCASE,
            phone TEXT,
            location TEXT
        )
        """)

        # VOLUNTEERS
        c.execute("""
        CREATE TABLE IF NOT EXISTS volunteers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            age INTEGER,
            email TEXT UNIQUE COLLATE NOCASE,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # MISSING PERSONS
        c.execute("""
        CREATE TABLE IF NOT EXISTS missing_persons(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            location TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ADMINS
        c.execute("""
        CREATE TABLE IF NOT EXISTS admins(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
        """)

        # DEFAULT ADMIN
        if not c.execute("SELECT id FROM admins WHERE username='admin'").fetchone():
            c.execute(
                "INSERT INTO admins(username,password) VALUES(?,?)",
                ("admin", generate_password_hash("admin123"))
            )

        conn.commit()


init_db()


# =====================================================
# HOME
# =====================================================

@app.route("/")
def home():
    return render_template("index.html")


# =====================================================
# STATIC PAGES (match template names)
# =====================================================

@app.route("/about")
def about():
    return render_template("aboutus.html")


@app.route("/contacts")
def contacts():
    return render_template("contacts.html")


@app.route("/donation")
def donation():
    return render_template("donation.html")


@app.route("/firstaid")
def firstaid():
    return render_template("firstaid.html")


@app.route("/protection")
def protection():
    return render_template("protecthome.html")


@app.route("/routes")
def routes():
    return render_template("routes.html")


@app.route("/alerts")
def alerts():
    return render_template("alerts.html")

@app.route("/user")
def user():
    return render_template("user.html")



@app.route("/map")
def map():
    return render_template("map.html")


@app.route("/emergency")
def emergency():
    return render_template("emergency.html")


# =====================================================
# USER REGISTER
# =====================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":

        email = request.form["email"].lower()
        phone = request.form["phone"]
        location = request.form["location"]

        with get_db() as conn:

            if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                flash("Email already registered", "error")
                return redirect(url_for("register"))

            conn.execute(
                "INSERT INTO users(email,phone,location) VALUES(?,?,?)",
                (email, phone, location)
            )
            conn.commit()

        flash("Registered successfully", "success")

    return render_template("register.html")


# =====================================================
# VOLUNTEERS
# =====================================================

@app.route("/volunteer/enroll", methods=["GET", "POST"])
def volunteer_enroll():

    if request.method == "POST":

        email = request.form["email"].lower()

        with get_db() as conn:

            if conn.execute("SELECT id FROM volunteers WHERE email=?", (email,)).fetchone():
                flash("Volunteer already exists", "error")
                return redirect(url_for("volunteer_enroll"))

            conn.execute(
                "INSERT INTO volunteers(name,age,email,phone) VALUES(?,?,?,?)",
                (
                    request.form["name"],
                    request.form["age"],
                    email,
                    request.form["phone"]
                )
            )
            conn.commit()

        flash("Volunteer added successfully", "success")
        return redirect(url_for("volunteers"))

    return render_template("volunteer_enroll.html")


@app.route("/volunteers")
def volunteers():
    with get_db() as conn:
        vols = conn.execute("SELECT * FROM volunteers ORDER BY id DESC").fetchall()

    return render_template(
        "volunteers.html",
        volunteers=vols,
        is_admin=session.get("admin_logged_in")
    )


@app.route("/volunteer/delete/<int:vol_id>", methods=["POST"])
def delete_volunteer(vol_id):
    with get_db() as conn:
        conn.execute("DELETE FROM volunteers WHERE id=?", (vol_id,))
        conn.commit()

    return redirect(url_for("volunteers"))


@app.route("/admin/delete_volunteer/<int:vol_id>", methods=["POST"])
def admin_delete_volunteer(vol_id):
    with get_db() as conn:
        conn.execute("DELETE FROM volunteers WHERE id=?", (vol_id,))
        conn.commit()

    flash("Volunteer deleted", "success")
    return redirect(url_for("admin_dashboard"))


# =====================================================
# MISSING PERSONS
# =====================================================

@app.route("/missing")
def missing():
    with get_db() as conn:
        persons = conn.execute("SELECT * FROM missing_persons ORDER BY id DESC").fetchall()

    return render_template("missing.html", persons=persons)


@app.route("/report-missing", methods=["POST"])
def report_missing():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO missing_persons(name,location,description) VALUES(?,?,?)",
            (
                request.form["name"],
                request.form["location"],
                request.form["description"]
            )
        )
        conn.commit()

    flash("Report submitted", "success")
    return redirect(url_for("missing"))


# =====================================================
# ADMIN
# =====================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form["username"]
        password = request.form["password"]

        with get_db() as conn:
            admin = conn.execute(
                "SELECT password FROM admins WHERE username=?",
                (username,)
            ).fetchone()

        if admin and check_password_hash(admin["password"], password):
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))

        flash("Invalid credentials", "error")

    return render_template("admin_login.html")


@app.route("/admin/dashboard", methods=["GET", "POST"])
def admin_dashboard():

    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    with get_db() as conn:
        users = conn.execute("SELECT * FROM users").fetchall()
        volunteers = conn.execute("SELECT * FROM volunteers").fetchall()
        alerts = conn.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()

    return render_template(
        "admin_dashboard.html",
        users=users,
        volunteers=volunteers,   # ⭐ added
        alerts=alerts
    )


    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    with get_db() as conn:
        users = conn.execute("SELECT * FROM users").fetchall()

    return render_template("admin_dashboard.html", users=users)


@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("home"))


# =====================================================
# START
# =====================================================

if __name__ == "__main__":
    app.run(debug=True)
