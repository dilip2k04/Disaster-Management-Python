from flask import Flask, request, render_template, redirect, url_for, session, flash, g
import sqlite3
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from twilio.rest import Client
from concurrent.futures import ThreadPoolExecutor

import cloudinary
import cloudinary.uploader


# =====================================================
# INIT
# =====================================================

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

DB_NAME = "users.db"


# =====================================================
# DATABASE (PRO STYLE)
# =====================================================

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_NAME)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DB_NAME)
    c = db.cursor()

    tables = [

        """CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            phone TEXT,
            location TEXT
        )""",

        """CREATE TABLE IF NOT EXISTS volunteers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            age INTEGER,
            email TEXT UNIQUE,
            phone TEXT,
            profile_pic_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

        """CREATE TABLE IF NOT EXISTS missing_persons(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            age INTEGER,
            gender TEXT,
            location TEXT,
            date_seen TEXT,
            description TEXT,
            notes TEXT,
            reporter_name TEXT,
            reporter_contact TEXT,
            reporter_relation TEXT,
            photo_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",

        """CREATE TABLE IF NOT EXISTS admins(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )""",

        """CREATE TABLE IF NOT EXISTS alerts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    ]

    for t in tables:
        c.execute(t)

    if not c.execute("SELECT id FROM admins WHERE username='admin'").fetchone():
        c.execute(
            "INSERT INTO admins(username,password) VALUES(?,?)",
            ("admin", generate_password_hash("admin123"))
        )

    db.commit()
    db.close()


init_db()


# =====================================================
# SERVICES (CLEAN ARCHITECTURE)
# =====================================================

TWILIO_CLIENT = Client(os.getenv("TWILIO_SID"), os.getenv("TWILIO_TOKEN"))


def send_sms(phone, text):
    if not phone:
        return
    try:
        TWILIO_CLIENT.messages.create(
            body=text,
            from_=os.getenv("TWILIO_PHONE"),
            to=phone.strip()
        )
    except Exception as e:
        print("SMS error:", e)


def send_email_bulk(recipients, subject, text):
    try:
        with smtplib.SMTP_SSL(os.getenv("EMAIL_HOST"), int(os.getenv("EMAIL_PORT"))) as server:
            server.login(os.getenv("EMAIL_USER"), os.getenv("EMAIL_PASS"))

            for email in recipients:
                if not email:
                    continue
                msg = MIMEText(text)
                msg["Subject"] = subject
                msg["From"] = os.getenv("EMAIL_USER")
                msg["To"] = email
                server.send_message(msg)

    except Exception as e:
        print("Email error:", e)


def broadcast_alert(title, message, location=None):
    text = f"🚨 ALERT: {title}\n\n{message}"

    db = get_db()

    if location:
        users = db.execute(
            "SELECT phone,email FROM users WHERE location=?",
            (location,)
        ).fetchall()
    else:
        users = db.execute("SELECT phone,email FROM users").fetchall()

    phones = [u["phone"] for u in users]
    emails = [u["email"] for u in users]

    # parallel SMS
    with ThreadPoolExecutor(max_workers=10) as executor:
        for phone in phones:
            executor.submit(send_sms, phone, text)

    # bulk email
    send_email_bulk(emails, title, text)


# =====================================================
# ROUTES
# =====================================================

@app.route("/")
def home():
    return render_template("index.html")


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


@app.route("/map")
def map():
    return render_template("map.html")


@app.route("/emergency")
def emergency():
    return render_template("emergency.html")


@app.route("/user")
def user():
    return render_template("user.html")


@app.route("/alerts")
def alerts():
    alerts = get_db().execute(
        "SELECT * FROM alerts ORDER BY id DESC"
    ).fetchall()
    return render_template("alerts.html", alerts=alerts)


@app.route("/missing")
def missing():
    persons = get_db().execute(
        "SELECT * FROM missing_persons"
    ).fetchall()
    return render_template("missing.html", persons=persons)


@app.route("/register", methods=["POST", "GET"])
def register():
    if request.method == "POST":
        db = get_db()
        db.execute(
            "INSERT INTO users(email,phone,location) VALUES(?,?,?)",
            (request.form["email"], request.form["phone"], request.form["location"])
        )
        db.commit()
        flash("Registered successfully")

    return render_template("register.html")


# =====================================================
# VOLUNTEER ENROLL
# =====================================================

@app.route("/volunteer/enroll", methods=["GET", "POST"])
def volunteer_enroll():

    if request.method == "POST":

        profile_url = None
        file = request.files.get("profile_pic")

        # upload image
        if file and file.filename:
            upload = cloudinary.uploader.upload(file)
            profile_url = upload["secure_url"]

        with get_db() as conn:
            conn.execute("""
                INSERT INTO volunteers(name,age,email,phone,profile_pic_url)
                VALUES (?,?,?,?,?)
            """, (
                request.form["name"],
                request.form["age"],
                request.form["email"],
                request.form["phone"],
                profile_url
            ))
            conn.commit()

        flash("Volunteer registered successfully", "success")
        return redirect(url_for("volunteers"))

    return render_template("volunteer_enroll.html")


    if request.method == "POST":
        db = get_db()

        db.execute(
            "INSERT INTO volunteers(name,age,email,phone) VALUES(?,?,?,?)",
            (
                request.form["name"],
                request.form["age"],
                request.form["email"],
                request.form["phone"]
            )
        )
        db.commit()

        flash("Volunteer registered successfully")
        return redirect(url_for("volunteers"))

    return render_template("volunteer_enroll.html")

@app.route("/report-missing", methods=["POST"])
def report_missing():

    photo_url = None

    # upload image to cloudinary
    file = request.files.get("photo")

    if file and file.filename:
        upload_result = cloudinary.uploader.upload(file)
        photo_url = upload_result["secure_url"]

    with get_db() as conn:
        conn.execute("""
            INSERT INTO missing_persons(
                name, age, gender, location, date_seen,
                description, notes,
                reporter_name, reporter_contact, reporter_relation,
                photo_url
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            request.form["name"],
            request.form["age"],
            request.form["gender"],
            request.form["location"],
            request.form["date"],
            request.form["description"],
            request.form.get("notes"),
            request.form["reporter_name"],
            request.form["reporter_contact"],
            request.form["reporter_relation"],
            photo_url
        ))
        conn.commit()

    flash("Missing person reported successfully")
    return redirect(url_for("missing"))


# =====================================================
# VOLUNTEERS LIST
# =====================================================

@app.route("/volunteers")
def volunteers():
    db = get_db()

    volunteers = db.execute(
        "SELECT * FROM volunteers ORDER BY id DESC"
    ).fetchall()

    return render_template("volunteers.html", volunteers=volunteers)


# =====================================================
# ADMIN
# =====================================================

@app.route("/admin/login", methods=["POST", "GET"])
def admin_login():

    if request.method == "POST":
        admin = get_db().execute(
            "SELECT password FROM admins WHERE username=?",
            (request.form["username"],)
        ).fetchone()

        if admin and check_password_hash(admin["password"], request.form["password"]):
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))

        flash("Invalid login")

    return render_template("admin_login.html")


@app.route("/admin/dashboard")
def admin_dashboard():

    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db()

    return render_template(
        "admin_dashboard.html",
        users=db.execute("SELECT * FROM users").fetchall(),
        volunteers=db.execute("SELECT * FROM volunteers").fetchall(),
        alerts=db.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()
    )


@app.route("/admin/add_alert", methods=["POST"])
def add_alert():

    title = request.form["title"]
    message = request.form["message"]
    location = request.form.get("location")

    db = get_db()
    db.execute(
        "INSERT INTO alerts(title,message) VALUES(?,?)",
        (title, message)
    )
    db.commit()

    broadcast_alert(title, message, location)

    flash("Alert sent successfully")
    return redirect(url_for("admin_dashboard"))

# =====================================================
# DELETE USER (ADMIN)
# =====================================================

@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):

    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db()

    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()

    flash("User deleted successfully")
    return redirect(url_for("admin_dashboard"))

# =====================================================
# DELETE VOLUNTEER (ADMIN)
# =====================================================

@app.route("/admin/delete_volunteer/<int:vol_id>", methods=["POST"])
def admin_delete_volunteer(vol_id):

    # security check
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db()

    db.execute(
        "DELETE FROM volunteers WHERE id=?",
        (vol_id,)
    )
    db.commit()

    flash("Volunteer deleted successfully", "success")

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
