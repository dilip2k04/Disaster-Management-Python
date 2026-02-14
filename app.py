from email.mime import text
from flask import Flask, request, render_template, redirect, url_for, session, flash, g, jsonify
import sqlite3
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from twilio.rest import Client
from concurrent.futures import ThreadPoolExecutor
import socket
import time

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

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE")

TWILIO_CLIENT = None
if TWILIO_SID and TWILIO_TOKEN:
    try:
        TWILIO_CLIENT = Client(TWILIO_SID, TWILIO_TOKEN)
    except Exception as e:
        print("Twilio init error:", e)


def send_sms(phone, text):
    if not phone or not TWILIO_CLIENT or not TWILIO_PHONE:
        return

    try:
        TWILIO_CLIENT.messages.create(
            body=text,
            from_=TWILIO_PHONE,
            to=phone.strip()
        )
    except Exception as e:
        print("SMS error:", e)


def send_email_bulk(recipients, subject, text):
    if not recipients:
        return

    host = os.getenv("EMAIL_HOST")
    port = os.getenv("EMAIL_PORT")
    user = os.getenv("EMAIL_USER")
    pwd = os.getenv("EMAIL_PASS")

    # Skip if config missing
    if not all([host, port, user, pwd]):
        print("Email config missing — skipping email")
        return

    try:
        # Set a timeout for the connection
        timeout = 10  # 10 seconds timeout
        
        # Create connection with timeout
        with smtplib.SMTP_SSL(host, int(port), timeout=timeout) as server:
            server.login(user, pwd)

            for email in recipients:
                if not email:
                    continue

                msg = MIMEText(text)
                msg["Subject"] = subject
                msg["From"] = user
                msg["To"] = email

                server.send_message(msg)
                print(f"Email sent to {email}")

    except socket.timeout:
        print("Email error: Connection timeout")
    except Exception as e:
        print("Email error:", str(e))


def broadcast_alert(title, message, location=None):
    alert_text = f"🚨 ALERT: {title}\n\n{message}"
    db = get_db()

    if location:
        users = db.execute(
            "SELECT phone,email FROM users WHERE location=?",
            (location,)
        ).fetchall()
    else:
        users = db.execute(
            "SELECT phone,email FROM users"
        ).fetchall()

    phones = [u["phone"] for u in users if u["phone"]]
    emails = [u["email"] for u in users if u["email"]]

    if not phones and not emails:
        print("No users registered — skipping broadcast")
        return 0

    # Send SMS
    if phones:
        with ThreadPoolExecutor(max_workers=5) as executor:
            for phone in phones:
                executor.submit(send_sms, phone, alert_text)

    # Send Email (in a separate thread to avoid timeout)
    if emails:
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(send_email_bulk, emails, title, alert_text)

    return max(len(phones), len(emails))


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


@app.route("/api/disasters")
def api_disasters():
    db = get_db()

    alerts = db.execute("""
        SELECT id, title, message, created_at
        FROM alerts
        ORDER BY id DESC
    """).fetchall()

    result = []

    for a in alerts:
        result.append({
            "id": a["id"],
            "disaster_type": a["title"],
            "location": "General Area",
            "datetime": a["created_at"],
            "message": a["message"]
        })

    return jsonify(result)


@app.route("/missing")
def missing():
    persons = get_db().execute(
        "SELECT * FROM missing_persons"
    ).fetchall()
    return render_template("missing.html", persons=persons)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        phone = request.form["phone"]
        location = request.form["location"]

        db = get_db()

        # Check duplicate first
        existing = db.execute(
            "SELECT id FROM users WHERE email=?",
            (email,)
        ).fetchone()

        if existing:
            return render_template(
                "register.html",
                error="⚠️ Email already registered. Please login instead."
            )

        db.execute(
            "INSERT INTO users(email,phone,location) VALUES(?,?,?)",
            (email, phone, location)
        )
        db.commit()

        return render_template(
            "register.html",
            message="✅ Registered successfully! You will now receive alerts."
        )

    return render_template("register.html")


# =====================================================
# VOLUNTEER ENROLL
# =====================================================

@app.route("/volunteer/enroll", methods=["GET", "POST"])
def volunteer_enroll():
    if request.method == "POST":
        db = get_db()

        email = request.form["email"]

        # Check duplicate first
        existing = db.execute(
            "SELECT id FROM volunteers WHERE email=?",
            (email,)
        ).fetchone()

        if existing:
            flash("⚠️ This email is already registered as a volunteer.", "error")
            return redirect(url_for("volunteer_enroll"))

        profile_url = None
        file = request.files.get("profile_pic")

        if file and file.filename:
            upload = cloudinary.uploader.upload(file)
            profile_url = upload["secure_url"]

        db.execute("""
            INSERT INTO volunteers(name,age,email,phone,profile_pic_url)
            VALUES (?,?,?,?,?)
        """, (
            request.form["name"],
            request.form["age"],
            email,
            request.form["phone"],
            profile_url
        ))

        db.commit()

        flash("✅ Volunteer registered successfully", "success")
        return redirect(url_for("volunteers"))

    return render_template("volunteer_enroll.html")


@app.route("/report-missing", methods=["POST"])
def report_missing():
    photo_url = None

    # Upload image to cloudinary
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
            request.form["date_seen"],
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
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    title = request.form.get("title")
    message = request.form.get("message")
    location = request.form.get("location")

    if not title or not message:
        flash("Title and message required", "error")
        return redirect(url_for("admin_dashboard"))

    db = get_db()

    try:
        db.execute(
            "INSERT INTO alerts(title,message) VALUES(?,?)",
            (title, message)
        )
        db.commit()
    except Exception as e:
        print("DB error:", e)
        flash("Database error", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        # Run broadcast in a separate thread to avoid timeout
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(broadcast_alert, title, message, location)
            recipients = future.result(timeout=30)  # 30 second timeout
    except Exception as e:
        print("Broadcast error:", e)
        recipients = 0

    if recipients > 0:
        flash(f"✅ Alert stored and sent to {recipients} users", "success")
    else:
        flash("⚠️ Alert stored, but no users received it", "warning")

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