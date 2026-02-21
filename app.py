from email.mime.text import MIMEText
from flask import Flask, request, render_template, redirect, url_for, session, flash, g, jsonify
import sqlite3
import os
import smtplib
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash   
from twilio.rest import Client
from concurrent.futures import ThreadPoolExecutor
from flask_cors import CORS
import cloudinary
import cloudinary.uploader
from datetime import datetime

# =====================================================
# INIT
# =====================================================

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")
CORS(app, supports_credentials=True)

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

DB_NAME = "users.db"

# =====================================================
# DATABASE
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
            location TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        
        """CREATE TABLE IF NOT EXISTS volunteers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            age INTEGER,
            email TEXT UNIQUE,
            phone TEXT,
            profile_pic_url TEXT,
            skills TEXT,
            availability TEXT DEFAULT 'on-call',
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
            status TEXT DEFAULT 'active',
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
            location TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    ]

    for t in tables:
        c.execute(t)

    # Add new columns if they don't exist (for existing databases)
    try:
        c.execute("ALTER TABLE volunteers ADD COLUMN skills TEXT")
    except:
        pass
    
    try:
        c.execute("ALTER TABLE volunteers ADD COLUMN availability TEXT DEFAULT 'on-call'")
    except:
        pass
    
    try:
        c.execute("ALTER TABLE missing_persons ADD COLUMN status TEXT DEFAULT 'active'")
    except:
        pass
    
    try:
        c.execute("ALTER TABLE alerts ADD COLUMN location TEXT")
    except:
        pass

    # Create default admin if not exists
    if not c.execute("SELECT id FROM admins WHERE username='admin'").fetchone():
        c.execute(
            "INSERT INTO admins(username,password) VALUES(?,?)",
            ("admin", generate_password_hash("admin123"))
        )

    db.commit()
    db.close()

init_db()

# =====================================================
# SERVICES
# =====================================================

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE")

TWILIO_CLIENT = None
if TWILIO_SID and TWILIO_TOKEN:
    try:
        TWILIO_CLIENT = Client(TWILIO_SID, TWILIO_TOKEN)
        print("✅ Twilio client initialized successfully")
    except Exception as e:
        print("❌ Twilio init error:", e)
else:
    print("⚠️ Twilio credentials not found in .env file")

def send_sms(phone, text):
    if not phone:
        print("❌ No phone number provided")
        return False
    
    if not TWILIO_CLIENT:
        print("❌ Twilio client not initialized")
        return False
    
    if not TWILIO_PHONE:
        print("❌ Twilio phone number not set")
        return False
    
    try:
        # Ensure phone number has + prefix
        if not phone.startswith('+'):
            phone = f"+91{phone}"  # Default to India if no prefix
        
        print(f"📱 Attempting to send SMS to {phone}")
        
        message = TWILIO_CLIENT.messages.create(
            body=text,
            from_=TWILIO_PHONE,
            to=phone
        )
        
        print(f"✅ SMS sent successfully to {phone}, SID: {message.sid}")
        return True
        
    except Exception as e:
        print(f"❌ SMS error for {phone}: {str(e)}")
        return False

def send_email_bulk(recipients, subject, text):
    host = os.getenv("EMAIL_HOST")
    port = os.getenv("EMAIL_PORT")
    user = os.getenv("EMAIL_USER")
    pwd = os.getenv("EMAIL_PASS")

    if not all([host, port, user, pwd]):
        print("❌ Email config missing — skipping email")
        print(f"Host: {host}, Port: {port}, User: {user}, Pass set: {bool(pwd)}")
        return 0

    sent_count = 0
    
    try:
        print(f"📧 Connecting to email server: {host}:{port}")
        with smtplib.SMTP_SSL(host, int(port)) as server:
            server.login(user, pwd)
            print("✅ Email login successful")
            
            for email in recipients:
                if not email:
                    continue
                    
                try:
                    msg = MIMEText(text)
                    msg["Subject"] = subject
                    msg["From"] = user
                    msg["To"] = email
                    
                    server.send_message(msg)
                    print(f"✅ Email sent to: {email}")
                    sent_count += 1
                    
                except Exception as e:
                    print(f"❌ Failed to send email to {email}: {e}")
                    
        return sent_count
        
    except Exception as e:
        print(f"❌ Email server error: {e}")
        return 0

def broadcast_alert(title, message, location=None):
    text = f"🚨 ALERT: {title}\n\n{message}"
    db = get_db()
    
    print(f"📢 Broadcasting alert: {title}")
    print(f"Location filter: {location or 'ALL'}")

    if location:
        users = db.execute(
            "SELECT phone,email FROM users WHERE location=?", (location,)
        ).fetchall()
        print(f"📍 Found {len(users)} users in location: {location}")
    else:
        users = db.execute("SELECT phone,email FROM users").fetchall()
        print(f"👥 Found {len(users)} total users")

    phones = [u["phone"] for u in users if u["phone"]]
    emails = [u["email"] for u in users if u["email"]]

    print(f"📱 Phones to notify: {len(phones)}")
    print(f"📧 Emails to notify: {len(emails)}")

    if not phones and not emails:
        print("⚠️ No users registered — skipping broadcast")
        return 0

    sms_sent = 0
    email_sent = 0
    
    # Send SMS
    if phones:
        print(f"📱 Sending SMS to {len(phones)} numbers...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for phone in phones:
                future = executor.submit(send_sms, phone, text)
                futures.append(future)
            
            # Wait for all SMS to complete
            for future in futures:
                try:
                    if future.result(timeout=10):
                        sms_sent += 1
                except Exception as e:
                    print(f"❌ SMS send error: {e}")

    # Send Email
    if emails:
        print(f"📧 Sending emails to {len(emails)} addresses...")
        email_sent = send_email_bulk(emails, title, text)

    total_sent = max(sms_sent, email_sent)
    print(f"✅ Broadcast complete: {total_sent} recipients notified")
    return total_sent

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
    alerts = get_db().execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()
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

# =====================================================
# MISSING PERSONS PAGES
# =====================================================

@app.route("/missing")
def missing():
    """Display all missing persons reports"""
    db = get_db()
    persons = db.execute("""
        SELECT * FROM missing_persons 
        ORDER BY 
            CASE WHEN status = 'active' THEN 0 ELSE 1 END,
            created_at DESC
    """).fetchall()
    
    # Get unique locations count for stats
    locations = db.execute("SELECT DISTINCT location FROM missing_persons").fetchall()
    
    return render_template(
        "missing.html", 
        persons=persons,
        location_count=len(locations)
    )

@app.route("/missing/update-status/<int:person_id>", methods=["POST"])
def update_missing_status(person_id):
    """Update status of a missing person report (admin only)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    new_status = data.get("status", "active")
    
    db = get_db()
    try:
        db.execute(
            "UPDATE missing_persons SET status=? WHERE id=?",
            (new_status, person_id)
        )
        db.commit()
        return jsonify({"message": "Status updated successfully"}), 200
    except Exception as e:
        print(f"Update error: {e}")
        return jsonify({"error": "Failed to update status"}), 500

# =====================================================
# VOLUNTEER PAGES
# =====================================================

@app.route("/volunteers")
def volunteers():
    """Display all registered volunteers"""
    db = get_db()
    volunteers = db.execute("""
        SELECT id, name, age, email, phone, profile_pic_url, skills, availability, created_at
        FROM volunteers 
        ORDER BY created_at DESC
    """).fetchall()
    
    # Check if user is admin for delete functionality
    is_admin = session.get("admin_logged_in", False)
    
    return render_template(
        "volunteers.html", 
        volunteers=volunteers,
        is_admin=is_admin
    )

@app.route("/volunteer/enroll", methods=["GET", "POST"])
def volunteer_enroll():
    """Multi-step volunteer enrollment form"""
    if request.method == "POST":
        db = get_db()
        email = request.form["email"]

        # Check if email already exists
        existing = db.execute("SELECT id FROM volunteers WHERE email=?", (email,)).fetchone()
        if existing:
            flash("This email is already registered as a volunteer.", "error")
            return redirect(url_for("volunteer_enroll"))

        # Handle profile picture upload
        profile_url = None
        file = request.files.get("profile_pic")
        if file and file.filename:
            try:
                upload = cloudinary.uploader.upload(file)
                profile_url = upload["secure_url"]
            except Exception as e:
                print(f"Cloudinary upload error: {e}")
                flash("Profile picture upload failed. You can continue without it.", "warning")

        # Get skills from form (if any)
        skills = request.form.get("skills", "")
        
        # Get availability
        availability = request.form.get("availability", "on-call")

        try:
            db.execute("""
                INSERT INTO volunteers(name, age, email, phone, profile_pic_url, skills, availability)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                request.form["name"],
                request.form["age"],
                email,
                request.form["phone"],
                profile_url,
                skills,
                availability
            ))
            db.commit()
            
            flash("🎉 Welcome to the team! Your volunteer profile has been created successfully.", "success")
            return redirect(url_for("volunteers"))
            
        except Exception as e:
            print(f"Database error: {e}")
            flash("Registration failed. Please try again.", "error")
            return redirect(url_for("volunteer_enroll"))

    return render_template("volunteer_enroll.html")

@app.route("/volunteer/delete/<int:vol_id>", methods=["POST"])
def delete_volunteer(vol_id):
    """Delete a volunteer (admin only)"""
    if not session.get("admin_logged_in"):
        flash("Unauthorized access", "error")
        return redirect(url_for("admin_login"))
    
    db = get_db()
    try:
        db.execute("DELETE FROM volunteers WHERE id=?", (vol_id,))
        db.commit()
        flash("Volunteer removed successfully", "success")
    except Exception as e:
        print(f"Delete error: {e}")
        flash("Failed to delete volunteer", "error")
    
    return redirect(url_for("volunteers"))

# ────────────────────────────────────────────────
# REGISTER (SINGLE CLEAN VERSION)
# ────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    # Handle JSON (mobile) or form-data (web)
    if request.is_json:
        data = request.get_json()
        email = data.get("email", "").strip().lower()
        phone = data.get("phone", "").strip()
        location = data.get("location", "").strip()
    else:
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        location = request.form.get("location", "").strip()

    # Validate required fields
    if not all([email, phone, location]):
        if request.is_json:
            return jsonify({"error": "All fields required"}), 400
        return render_template("register.html", error="All fields required")

    # Validate phone number (should be 10 digits)
    if not phone.isdigit() or len(phone) != 10:
        if request.is_json:
            return jsonify({"error": "Phone must be 10 digits"}), 400
        return render_template("register.html", error="Phone number must be exactly 10 digits")

    # Add +91 prefix to phone number
    phone_with_prefix = f"+91{phone}"

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()

    if existing:
        if request.is_json:
            return jsonify({"error": "Email already registered"}), 409
        return render_template("register.html", error="⚠️ Email already registered. Please login instead.")

    try:
        db.execute(
            "INSERT INTO users(email, phone, location, created_at) VALUES(?,?,?,?)",
            (email, phone_with_prefix, location, datetime.now())
        )
        db.commit()
        print(f"✅ User registered: {email}, {phone_with_prefix}, {location}")
    except Exception as e:
        print(f"❌ Database error: {e}")
        if request.is_json:
            return jsonify({"error": "Registration failed"}), 500
        return render_template("register.html", error="Registration failed. Please try again.")

    if request.is_json:
        return jsonify({"message": "Registered successfully"}), 201
    else:
        return render_template("register.html", message="✅ Registered successfully! You will now receive alerts.")

# =====================================================
# ADMIN ROUTES
# =====================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        admin = get_db().execute(
            "SELECT password FROM admins WHERE username=?", (request.form["username"],)
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
        users=db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall(),
        volunteers=db.execute("SELECT * FROM volunteers ORDER BY created_at DESC").fetchall(),
        alerts=db.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall(),
        missing_persons=db.execute("SELECT * FROM missing_persons ORDER BY created_at DESC").fetchall()
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
    db.execute(
        "INSERT INTO alerts(title, message, location) VALUES(?,?,?)", 
        (title, message, location)
    )
    db.commit()

    recipients = broadcast_alert(title, message, location)

    if recipients > 0:
        flash(f"✅ Alert stored and sent to {recipients} users", "success")
    else:
        flash("⚠️ Alert stored, but no users received it", "warning")

    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db()
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    flash("User deleted successfully")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete_volunteer/<int:vol_id>", methods=["POST"])
def admin_delete_volunteer(vol_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db()
    db.execute("DELETE FROM volunteers WHERE id=?", (vol_id,))
    db.commit()
    flash("Volunteer deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete_missing/<int:person_id>", methods=["POST"])
def admin_delete_missing(person_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    db = get_db()
    db.execute("DELETE FROM missing_persons WHERE id=?", (person_id,))
    db.commit()
    flash("Missing person record deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("home"))

# =====================================================
# API ROUTES FOR REACT NATIVE APP
# =====================================================

@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    """Get all registered users (admin only)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    users = db.execute("""
        SELECT id, email, phone, location, created_at
        FROM users 
        ORDER BY created_at DESC
    """).fetchall()
    
    result = []
    for user in users:
        result.append({
            "id": user["id"],
            "email": user["email"],
            "phone": user["phone"],
            "location": user["location"],
            "created_at": user["created_at"]
        })
    
    return jsonify(result)

@app.route("/api/admin/volunteers", methods=["GET"])
def api_admin_volunteers():
    """Get all volunteers (admin only)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    volunteers = db.execute("""
        SELECT id, name, age, email, phone, profile_pic_url, skills, availability, created_at
        FROM volunteers 
        ORDER BY created_at DESC
    """).fetchall()
    
    result = []
    for v in volunteers:
        result.append({
            "id": v["id"],
            "name": v["name"],
            "age": v["age"],
            "email": v["email"],
            "phone": v["phone"],
            "profile_pic": v["profile_pic_url"],
            "skills": v["skills"].split(",") if v["skills"] else [],
            "availability": v["availability"],
            "created_at": v["created_at"]
        })
    
    return jsonify(result)

@app.route("/api/admin/alerts", methods=["GET"])
def api_admin_alerts():
    """Get all alerts (admin only)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    alerts = db.execute("""
        SELECT id, title, message, location, created_at
        FROM alerts 
        ORDER BY created_at DESC
    """).fetchall()
    
    result = []
    for a in alerts:
        result.append({
            "id": a["id"],
            "title": a["title"],
            "message": a["message"],
            "location": a["location"],
            "created_at": a["created_at"]
        })
    
    return jsonify(result)

@app.route("/api/admin/delete_user/<int:user_id>", methods=["DELETE", "POST"])
def api_admin_delete_user(user_id):
    """Delete a user (admin only)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    
    # Check if user exists
    user = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    try:
        db.execute("DELETE FROM users WHERE id=?", (user_id,))
        db.commit()
        return jsonify({"message": "User deleted successfully"}), 200
    except Exception as e:
        print(f"Error deleting user: {e}")
        return jsonify({"error": "Failed to delete user"}), 500

@app.route("/api/admin/delete_volunteer/<int:vol_id>", methods=["DELETE", "POST"])
def api_admin_delete_volunteer(vol_id):
    """Delete a volunteer (admin only)"""
    if not session.get("admin_logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    
    db = get_db()
    
    # Check if volunteer exists
    vol = db.execute("SELECT id FROM volunteers WHERE id=?", (vol_id,)).fetchone()
    if not vol:
        return jsonify({"error": "Volunteer not found"}), 404
    
    try:
        db.execute("DELETE FROM volunteers WHERE id=?", (vol_id,))
        db.commit()
        return jsonify({"message": "Volunteer deleted successfully"}), 200
    except Exception as e:
        print(f"Error deleting volunteer: {e}")
        return jsonify({"error": "Failed to delete volunteer"}), 500

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    """Admin login API for React Native app"""
    data = request.get_json()
    
    if not data or not data.get("username") or not data.get("password"):
        return jsonify({"error": "Username and password required"}), 400
    
    admin = get_db().execute(
        "SELECT password FROM admins WHERE username=?", (data["username"],)
    ).fetchone()
    
    if admin and check_password_hash(admin["password"], data["password"]):
        session["admin_logged_in"] = True
        return jsonify({"message": "Login successful"}), 200
    
    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/admin/logout", methods=["POST"])
def api_admin_logout():
    """Admin logout API for React Native app"""
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200

@app.route("/api/admin/check_auth", methods=["GET"])
def api_admin_check_auth():
    """Check if admin is authenticated"""
    if session.get("admin_logged_in"):
        return jsonify({"authenticated": True}), 200
    return jsonify({"authenticated": False}), 401

# =====================================================
# PUBLIC API ROUTES FOR REACT NATIVE APP
# =====================================================

@app.route("/api/volunteers", methods=["GET"])
def api_volunteers():
    """Get all volunteers for React Native app"""
    db = get_db()
    volunteers = db.execute("""
        SELECT id, name, age, email, phone, profile_pic_url, skills, availability, created_at
        FROM volunteers 
        ORDER BY created_at DESC
    """).fetchall()
    
    result = []
    for v in volunteers:
        result.append({
            "id": v["id"],
            "name": v["name"],
            "age": v["age"],
            "email": v["email"],
            "phone": v["phone"],
            "profile_pic": v["profile_pic_url"],
            "skills": v["skills"].split(",") if v["skills"] else [],
            "availability": v["availability"],
            "joined": v["created_at"]
        })
    
    return jsonify(result)

@app.route("/api/missing-persons", methods=["GET"])
def api_missing_persons():
    """Get all missing persons for React Native app"""
    db = get_db()
    persons = db.execute("""
        SELECT * FROM missing_persons 
        WHERE status = 'active'
        ORDER BY created_at DESC
    """).fetchall()
    
    result = []
    for p in persons:
        result.append({
            "id": p["id"],
            "name": p["name"],
            "age": p["age"],
            "gender": p["gender"],
            "location": p["location"],
            "date_seen": p["date_seen"],
            "description": p["description"],
            "notes": p["notes"],
            "photo_url": p["photo_url"],
            "reporter_name": p["reporter_name"],
            "reporter_contact": p["reporter_contact"],
            "reporter_relation": p["reporter_relation"],
            "status": p["status"],
            "created_at": p["created_at"]
        })
    
    # Ensure we're returning JSON with proper headers
    response = jsonify(result)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response
    """Get all missing persons for React Native app"""
    db = get_db()
    persons = db.execute("""
        SELECT * FROM missing_persons 
        WHERE status = 'active'
        ORDER BY created_at DESC
    """).fetchall()
    
    result = []
    for p in persons:
        result.append({
            "id": p["id"],
            "name": p["name"],
            "age": p["age"],
            "gender": p["gender"],
            "location": p["location"],
            "date_seen": p["date_seen"],
            "description": p["description"],
            "notes": p["notes"],
            "photo_url": p["photo_url"],
            "reporter_name": p["reporter_name"],
            "reporter_contact": p["reporter_contact"],
            "reporter_relation": p["reporter_relation"],
            "status": p["status"],
            "created_at": p["created_at"]
        })
    
    return jsonify(result)

@app.route("/api/report-missing", methods=["POST"])
def api_report_missing():
    """API endpoint to report missing person from mobile app"""
    photo_url = None
    
    # Check if request has file
    if 'photo' in request.files:
        file = request.files['photo']
        if file and file.filename:
            try:
                upload_result = cloudinary.uploader.upload(file)
                photo_url = upload_result["secure_url"]
            except Exception as e:
                print(f"Cloudinary upload error: {e}")

    # Get form data
    data = request.form
    
    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO missing_persons(
                    name, age, gender, location, date_seen,
                    description, notes,
                    reporter_name, reporter_contact, reporter_relation,
                    photo_url, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'active')
            """, (
                data.get("name"),
                data.get("age"),
                data.get("gender"),
                data.get("location"),
                data.get("date_seen"),
                data.get("description"),
                data.get("notes", ""),
                data.get("reporter_name"),
                data.get("reporter_contact"),
                data.get("reporter_relation"),
                photo_url
            ))
            conn.commit()

        return jsonify({"message": "Report submitted successfully"}), 201
        
    except Exception as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Failed to submit report"}), 500

@app.route("/api/register", methods=["POST"])
def api_register():
    """API endpoint for mobile app registration"""
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "Invalid data"}), 400
    
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    location = data.get("location", "").strip()

    if not all([email, phone, location]):
        return jsonify({"error": "All fields required"}), 400

    if not phone.isdigit() or len(phone) != 10:
        return jsonify({"error": "Phone must be 10 digits"}), 400

    phone_with_prefix = f"+91{phone}"

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()

    if existing:
        return jsonify({"error": "Email already registered"}), 409

    try:
        db.execute(
            "INSERT INTO users(email, phone, location, created_at) VALUES(?,?,?,?)",
            (email, phone_with_prefix, location, datetime.now())
        )
        db.commit()
        return jsonify({"message": "Registered successfully"}), 201
    except Exception as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Registration failed"}), 500

# =====================================================
# UNIFIED REPORT MISSING ROUTE (Handles both web and mobile)
# =====================================================

@app.route("/report-missing", methods=["POST"])
def report_missing():
    """Submit a new missing person report (handles both web and mobile)"""
    
    # Check if this is an API request (from React Native)
    is_api_request = request.headers.get('Accept') == 'application/json' or request.headers.get('Content-Type') == 'application/json'
    
    photo_url = None
    file = request.files.get("photo")

    if file and file.filename:
        try:
            upload_result = cloudinary.uploader.upload(file)
            photo_url = upload_result["secure_url"]
        except Exception as e:
            print(f"Cloudinary upload error: {e}")
            if is_api_request:
                return jsonify({"error": "Photo upload failed"}), 500
            flash("Photo upload failed. You can continue without it.", "warning")

    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO missing_persons(
                    name, age, gender, location, date_seen,
                    description, notes,
                    reporter_name, reporter_contact, reporter_relation,
                    photo_url, status
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'active')
            """, (
                request.form["name"],
                request.form["age"],
                request.form["gender"],
                request.form["location"],
                request.form["date_seen"],
                request.form["description"],
                request.form.get("notes", ""),
                request.form["reporter_name"],
                request.form["reporter_contact"],
                request.form["reporter_relation"],
                photo_url
            ))
            conn.commit()

        # For API requests, return JSON
        if is_api_request:
            return jsonify({
                "message": "Missing person report submitted successfully",
                "id": conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            }), 201
        
        # For web requests, redirect with flash message
        flash("✅ Missing person report submitted successfully. Authorities have been notified.", "success")
        return redirect(url_for("missing"))
        
    except Exception as e:
        print(f"Database error: {e}")
        if is_api_request:
            return jsonify({"error": "Failed to submit report"}), 500
        flash("❌ Failed to submit report. Please try again.", "error")
        return redirect(url_for("missing"))

# =====================================================
# TEST ENDPOINT (for debugging)
# =====================================================

@app.route("/test-notification", methods=["GET"])
def test_notification():
    """Test endpoint to check SMS and email configuration"""
    results = {
        "twilio_configured": bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_PHONE),
        "email_configured": bool(os.getenv("EMAIL_HOST") and os.getenv("EMAIL_PORT") and 
                                 os.getenv("EMAIL_USER") and os.getenv("EMAIL_PASS")),
        "database": {
            "users": 0,
            "volunteers": 0,
            "missing_persons": 0,
            "alerts": 0
        }
    }
    
    db = get_db()
    results["database"]["users"] = db.execute("SELECT COUNT(*) as count FROM users").fetchone()["count"]
    results["database"]["volunteers"] = db.execute("SELECT COUNT(*) as count FROM volunteers").fetchone()["count"]
    results["database"]["missing_persons"] = db.execute("SELECT COUNT(*) as count FROM missing_persons").fetchone()["count"]
    results["database"]["alerts"] = db.execute("SELECT COUNT(*) as count FROM alerts").fetchone()["count"]
    
    return jsonify(results)

# =====================================================
# START
# =====================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Starting Disaster Alert System")
    print("=" * 60)
    print(f"✅ Twilio configured: {bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_PHONE)}")
    print(f"✅ Email configured: {bool(os.getenv('EMAIL_HOST') and os.getenv('EMAIL_PORT'))}")
    print(f"✅ Cloudinary configured: {bool(os.getenv('CLOUDINARY_CLOUD_NAME'))}")
    print("=" * 60)
    print("📱 API Endpoints Available:")
    print("   • GET  /api/disasters - Get all alerts")
    print("   • GET  /api/volunteers - Get all volunteers")
    print("   • GET  /api/missing-persons - Get missing persons")
    print("   • POST /api/register - User registration")
    print("   • POST /api/report-missing - Report missing person (mobile)")
    print("   • POST /report-missing - Report missing person (web/mobile unified)")
    print("   • POST /api/admin/login - Admin login")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)