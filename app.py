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


# =====================================================
# INIT
# =====================================================

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change_this_secret_key")

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
                "INSERT INTO admins(username,password) VALUES(?,?)",
                ("admin", generate_password_hash("admin123"))
            )

        conn.commit()


init_db()


# =====================================================
# EMAIL
# =====================================================

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")


def send_alert_email(to_email, location, msg_text):
    try:
        msg = MIMEText(f"🚨 Emergency Alert\n\nLocation: {location}\n\n{msg_text}")
        msg["Subject"] = "Emergency Alert"
        msg["From"] = EMAIL_USER
        msg["To"] = to_email

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)

    except Exception as e:
        print("Email failed:", e)


# =====================================================
# SMS
# =====================================================

twilio_client = Client(
    os.getenv("TWILIO_SID"),
    os.getenv("TWILIO_TOKEN")
)


def send_alert_sms(to_phone, location, msg_text):
    try:
        twilio_client.messages.create(
            body=f"🚨 ALERT at {location}\n{msg_text}",
            from_=os.getenv("TWILIO_PHONE"),
            to=to_phone
        )
    except:
        pass


cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)


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

    # upload to cloudinary
    if photo and photo.filename:
        result = cloudinary.uploader.upload(photo)
        photo_url = result["secure_url"]

    with get_db() as conn:
        conn.execute("""
            INSERT INTO missing_persons
            (name, age, gender, location, date_seen, description, notes,
             photo_url, reporter_name, reporter_contact, reporter_relation)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            request.form["name"],
            request.form["age"],
            request.form["gender"],
            request.form["location"],
            request.form["date"],
            request.form["description"],
            request.form.get("notes"),
            photo_url,
            request.form["reporter_name"],
            request.form["reporter_contact"],
            request.form["reporter_relation"]
        ))

        conn.commit()

    flash("Missing person reported successfully", "success")
    return redirect(url_for("missing"))

# =====================================================
# ROUTES
# =====================================================

@app.route("/")
def home():
    return render_template("index.html")


# =====================================================
# REGISTER
# =====================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        phone = request.form["phone"]
        location = request.form["location"]

        with get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(email,phone,location) VALUES(?,?,?)",
                (email, phone, location)
            )

        flash("Registered!", "success")
        return redirect(url_for("register"))

    return render_template("register.html")



# =====================================================
# ADMIN LOGIN
# =====================================================

# ==========================================
# MOBILE ADMIN LOGIN API (JSON)
# ==========================================

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.json

    username = data.get("username")
    password = data.get("password")

    with get_db() as conn:
        admin = conn.execute(
            "SELECT * FROM admins WHERE username=?",
            (username,)
        ).fetchone()

    if admin and check_password_hash(admin["password"], password):
        return jsonify({"success": True})

    return jsonify({"success": False}), 401

#mobile logics

@app.route("/api/admin/alert", methods=["POST"])
def api_send_alert():
    data = request.json

    disaster_type = data.get("disaster_type")
    location = data.get("location")
    datetime_ = data.get("datetime")
    message = data.get("message")

    with get_db() as conn:
        c = conn.cursor()

        # save alert
        c.execute("""
            INSERT INTO alerts(disaster_type,location,datetime,message)
            VALUES(?,?,?,?)
        """, (disaster_type, location, datetime_, message))

        # ✅ ALL USERS (no filter)
        users = c.execute(
            "SELECT email,phone FROM users"
        ).fetchall()

        print("USERS FOUND:", len(users))

        for u in users:
            print("Sending to:", u["email"], u["phone"])

            send_alert_email(u["email"], location, message)
            send_alert_sms(u["phone"], location, message)

        conn.commit()

    return jsonify({"success": True})

    data = request.json

    disaster_type = data.get("disaster_type")
    location = data.get("location")
    datetime_ = data.get("datetime")
    message = data.get("message")

    with get_db() as conn:
        c = conn.cursor()

        # save alert
        c.execute("""
            INSERT INTO alerts(disaster_type,location,datetime,message)
            VALUES(?,?,?,?)
        """, (disaster_type, location, datetime_, message))

        # fetch users (case-insensitive)
        users = c.execute(
            "SELECT email,phone FROM users WHERE LOWER(location)=LOWER(?)",
            (location,)
        ).fetchall()

        print("USERS FOUND:", len(users))

        for u in users:
            print("Sending to:", u["email"], u["phone"])

            send_alert_email(u["email"], location, message)
            send_alert_sms(u["phone"], location, message)

        conn.commit()

    return jsonify({"success": True})

    data = request.json

    disaster_type = data.get("disaster_type")
    location = data.get("location")
    datetime_ = data.get("datetime")
    message = data.get("message")

    print("ALERT RECEIVED:", disaster_type, location)

    with get_db() as conn:
        c = conn.cursor()

        c.execute("""
            INSERT INTO alerts(disaster_type,location,datetime,message)
            VALUES(?,?,?,?)
        """, (disaster_type, location, datetime_, message))

        users = c.execute(
            "SELECT email,phone FROM users WHERE location=?",
            (location,)
        ).fetchall()

        print("USERS FOUND:", len(users))  # 🔥 IMPORTANT

        for u in users:
            print("Sending to:", u["email"], u["phone"])

            threading.Thread(target=send_alert_email,
                             args=(u["email"], location, message)).start()

            threading.Thread(target=send_alert_sms,
                             args=(u["phone"], location, message)).start()

        conn.commit()

    return jsonify({"success": True})

    data = request.json

    disaster_type = data.get("disaster_type")
    location = data.get("location")
    datetime_ = data.get("datetime")
    message = data.get("message")

    with get_db() as conn:
        c = conn.cursor()

        # save alert
        c.execute("""
            INSERT INTO alerts(disaster_type,location,datetime,message)
            VALUES(?,?,?,?)
        """, (disaster_type, location, datetime_, message))

        # fetch users
        users = c.execute(
            "SELECT email,phone FROM users WHERE location=?",
            (location,)
        ).fetchall()

        # 🔥 SEND EMAIL + SMS (same as website)
        for u in users:
            threading.Thread(
                target=send_alert_email,
                args=(u["email"], location, message)
            ).start()

            threading.Thread(
                target=send_alert_sms,
                args=(u["phone"], location, message)
            ).start()

        conn.commit()

    return jsonify({"success": True})

    data = request.json

    disaster_type = data.get("disaster_type")
    location = data.get("location")
    datetime_ = data.get("datetime")
    message = data.get("message")

    with get_db() as conn:
        c = conn.cursor()

        c.execute("""
            INSERT INTO alerts(disaster_type,location,datetime,message)
            VALUES(?,?,?,?)
        """, (disaster_type, location, datetime_, message))

        conn.commit()

    return jsonify({"success": True})

    data = request.json

    with get_db() as conn:
        c = conn.cursor()

        c.execute("""
            INSERT INTO alerts(disaster_type,location,datetime,message)
            VALUES(?,?,?,?)
        """, (
            data["disaster_type"],
            data["location"],
            data["datetime"],
            data["message"]
        ))

        users = c.execute(
            "SELECT email,phone FROM users WHERE location=?",
            (data["location"],)
        ).fetchall()

        for u in users:
            threading.Thread(target=send_alert_email,
                             args=(u["email"], data["location"], data["message"])).start()

            threading.Thread(target=send_alert_sms,
                             args=(u["phone"], data["location"], data["message"])).start()

        conn.commit()

    return jsonify({"success": True})


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


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        with get_db() as conn:
            admin = conn.execute(
                "SELECT password FROM admins WHERE username=?",
                (request.form["username"],)
            ).fetchone()

        if admin and check_password_hash(admin["password"], request.form["password"]):
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))

        flash("Invalid credentials", "error")

    return render_template("admin_login.html")


# =====================================================
# ADMIN DASHBOARD
# =====================================================

@app.route("/admin/dashboard", methods=["GET", "POST"])
def admin_dashboard():

    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    with get_db() as conn:
        c = conn.cursor()

        # Send alert
        if request.method == "POST":
            disaster_type = request.form["disaster_type"]
            location = request.form["location"]
            datetime_ = request.form["datetime"]
            message = request.form["message"]

            c.execute("""
                INSERT INTO alerts(disaster_type,location,datetime,message)
                VALUES(?,?,?,?)
            """, (disaster_type, location, datetime_, message))

            users = c.execute(
                "SELECT email,phone FROM users WHERE location=?",
                (location,)
            ).fetchall()

            for u in users:
                threading.Thread(target=send_alert_email,
                                 args=(u["email"], location, message)).start()

                threading.Thread(target=send_alert_sms,
                                 args=(u["phone"], location, message)).start()

            flash("Alert sent!", "success")

        users = c.execute("SELECT * FROM users").fetchall()
        alerts = c.execute("SELECT * FROM alerts ORDER BY datetime DESC").fetchall()

    return render_template("admin_dashboard.html", users=users, alerts=alerts)


# =====================================================
# ✅ FIX FOR YOUR ERROR (DELETE USER ROUTE)
# =====================================================

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
# API FOR MAP / DISASTERS
# =====================================================

@app.route("/api/disasters")
def api_disasters():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM alerts").fetchall()
    return jsonify([dict(r) for r in rows])


# backward compatibility
@app.route("/get_disasters")
def get_disasters():
    return api_disasters()


# =====================================================
# STATIC PAGES
# =====================================================
# =====================================================
# STATIC PAGES (REQUIRED FOR NAVBAR LINKS)
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
