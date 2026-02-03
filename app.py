from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify
import sqlite3
import os
import threading
import smtplib
from email.mime.text import MIMEText
from werkzeug.security import generate_password_hash, check_password_hash
from twilio.rest import Client
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import time

# =====================================================
# INIT
# =====================================================

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change_this_secret_key_please")

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

        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            phone TEXT,
            location TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS admins(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS alerts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            disaster_type TEXT,
            location TEXT,
            datetime TEXT,
            message TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS missing_persons(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            age INTEGER,
            gender TEXT,
            location TEXT,
            date_seen TEXT,
            description TEXT,
            notes TEXT,
            photo_url TEXT,
            reporter_name TEXT,
            reporter_contact TEXT,
            reporter_relation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # default admin
        if not c.execute("SELECT id FROM admins WHERE username='admin'").fetchone():
            c.execute(
                "INSERT INTO admins(username, password) VALUES(?,?)",
                ("admin", generate_password_hash("admin123"))
            )

        conn.commit()


init_db()

# =====================================================
# EMAIL (Gmail version - consider switching to SendGrid/Resend)
# =====================================================

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")


def send_alert_email(to_email, location, msg_text):
    if not EMAIL_USER or not EMAIL_PASS:
        print("❌ EMAIL credentials not set in environment")
        return

    try:
        msg = MIMEText(f"""
🚨 Emergency Alert

Location: {location}

{msg_text}
""")
        msg["Subject"] = "🚨 Emergency Alert"
        msg["From"] = EMAIL_USER
        msg["To"] = to_email

        print(f"📧 Attempting to send email to: {to_email}")

        # Adding timeout to prevent hanging forever
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
        server.login(EMAIL_USER, EMAIL_PASS)
        server.send_message(msg)
        server.quit()

        print(f"✅ Email sent to {to_email}")

    except Exception as e:
        print(f"❌ Email failed to {to_email}: {str(e)}")


# =====================================================
# SMS - Twilio
# =====================================================

twilio_client = Client(
    os.getenv("TWILIO_SID"),
    os.getenv("TWILIO_TOKEN")
)


def send_alert_sms(to_phone, location, msg_text):
    try:
        if not to_phone or len(to_phone) < 8:
            print(f"Invalid phone number: {to_phone}")
            return

        twilio_client.messages.create(
            body=f"🚨 ALERT at {location}\n{msg_text}",
            from_=os.getenv("TWILIO_PHONE"),
            to=to_phone
        )
        print(f"✅ SMS sent to {to_phone}")
    except Exception as e:
        print(f"❌ SMS failed to {to_phone}: {str(e)}")


# =====================================================
# CLOUDINARY
# =====================================================

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)


# =====================================================
# MISSING PERSONS
# =====================================================

@app.route("/missing")
def missing():
    with get_db() as conn:
        persons = conn.execute(
            "SELECT * FROM missing_persons ORDER BY created_at DESC"
        ).fetchall()

    return render_template("missing.html", persons=persons)


@app.route("/report-missing", methods=["POST"])
def report_missing():
    photo = request.files.get("photo")
    photo_url = None

    if photo and photo.filename:
        try:
            result = cloudinary.uploader.upload(photo)
            photo_url = result["secure_url"]
        except Exception as e:
            print(f"Cloudinary upload failed: {e}")
            flash("Failed to upload photo", "error")

    with get_db() as conn:
        conn.execute("""
            INSERT INTO missing_persons
            (name, age, gender, location, date_seen, description, notes,
             photo_url, reporter_name, reporter_contact, reporter_relation)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            request.form.get("name"),
            request.form.get("age"),
            request.form.get("gender"),
            request.form.get("location"),
            request.form.get("date"),
            request.form.get("description"),
            request.form.get("notes"),
            photo_url,
            request.form.get("reporter_name"),
            request.form.get("reporter_contact"),
            request.form.get("reporter_relation")
        ))
        conn.commit()

    flash("Missing person reported successfully", "success")
    return redirect(url_for("missing"))


# =====================================================
# HOME & STATIC PAGES
# =====================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        phone = request.form.get("phone")
        location = request.form.get("location")

        if not email or not phone or not location:
            flash("All fields are required", "error")
            return redirect(url_for("register"))

        with get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(email, phone, location) VALUES(?,?,?)",
                (email, phone, location)
            )
            conn.commit()

        flash("Registered successfully!", "success")
        return redirect(url_for("register"))

    return render_template("register.html")


# =====================================================
# ADMIN LOGIN - WEB
# =====================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

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


# =====================================================
# ADMIN DASHBOARD - WEB
# =====================================================

@app.route("/admin/dashboard", methods=["GET", "POST"])
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    with get_db() as conn:
        c = conn.cursor()

        if request.method == "POST":
            disaster_type = request.form.get("disaster_type")
            location = request.form.get("location")
            datetime_str = request.form.get("datetime")
            message = request.form.get("message")

            if not all([disaster_type, location, message]):
                flash("Missing required fields", "error")
            else:
                c.execute("""
                    INSERT INTO alerts (disaster_type, location, datetime, message)
                    VALUES (?, ?, ?, ?)
                """, (disaster_type, location, datetime_str, message))

                users = c.execute(
                    "SELECT email, phone FROM users WHERE location = ?",
                    (location,)
                ).fetchall()

                for u in users:
                    threading.Thread(
                        target=send_alert_email,
                        args=(u["email"], location, message),
                        daemon=True
                    ).start()

                    threading.Thread(
                        target=send_alert_sms,
                        args=(u["phone"], location, message),
                        daemon=True
                    ).start()

                conn.commit()
                flash("Alert sent successfully!", "success")

        users = c.execute("SELECT * FROM users").fetchall()
        alerts = c.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()

    return render_template("admin_dashboard.html", users=users, alerts=alerts)


@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()

    flash("User deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))


# =====================================================
# MOBILE ADMIN API
# =====================================================

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json(silent=True) or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"success": False, "error": "Missing credentials"}), 400

    with get_db() as conn:
        admin = conn.execute(
            "SELECT password FROM admins WHERE username=?",
            (username,)
        ).fetchone()

    if admin and check_password_hash(admin["password"], password):
        return jsonify({"success": True})

    return jsonify({"success": False, "error": "Invalid credentials"}), 401


@app.route("/api/admin/alert", methods=["POST"])
def api_send_alert():
    data = request.get_json(silent=True) or {}

    disaster_type = data.get("disaster_type")
    location = data.get("location")
    datetime_str = data.get("datetime")
    message = data.get("message")

    if not all([disaster_type, location, message]):
        return jsonify({
            "success": False,
            "error": "Missing required fields: disaster_type, location, message"
        }), 400

    with get_db() as conn:
        c = conn.cursor()

        # Save the alert
        c.execute("""
            INSERT INTO alerts (disaster_type, location, datetime, message)
            VALUES (?, ?, ?, ?)
        """, (disaster_type, location, datetime_str, message))

        # Get users (case-insensitive match recommended)
        users = c.execute("""
            SELECT email, phone FROM users 
            WHERE LOWER(location) = LOWER(?)
        """, (location,)).fetchall()

        print(f"[ALERT] Found {len(users)} users for location: {location}")

        # Send notifications in background
        for user in users:
            email = user["email"]
            phone = user["phone"]

            if email and "@" in email:
                threading.Thread(
                    target=send_alert_email,
                    args=(email, location, message),
                    daemon=True
                ).start()

            if phone and len(str(phone).strip()) >= 8:
                threading.Thread(
                    target=send_alert_sms,
                    args=(phone, location, message),
                    daemon=True
                ).start()

        conn.commit()

    return jsonify({
        "success": True,
        "users_notified": len(users)
    })


@app.route("/api/admin/users")
def api_get_users():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/users/<int:id>", methods=["DELETE"])
def api_delete_user(id):
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (id,))
        conn.commit()
    return jsonify({"success": True})


# =====================================================
# API FOR MAP / DISASTERS
# =====================================================

@app.route("/api/disasters")
def api_disasters():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/get_disasters")
def get_disasters():
    return api_disasters()


# =====================================================
# STATIC PAGES
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


@app.route("/emergency")
def emergency():
    return render_template("emergency.html")


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)