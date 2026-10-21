import smtplib
import uuid
import time
import os
from collections import defaultdict
from email.mime.text import MIMEText

from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

from extractor import extract_text
from parser import parse_and_score, generate_test_questions, grade_test_submission
from database import (
    save_resume_result, create_table, create_test_invites_table, save_test_invite, get_test_invite,
    create_employers_table, create_employer, get_employer_by_email,
    create_jobs_table, create_job, get_jobs_for_employer, get_job,
    extend_resumes_table, get_resumes_for_job, delete_job, find_job_id_by_jd, start_assessment, save_assessment_result, get_round1_results, record_violation
)
from werkzeug.utils import secure_filename
from splitter import split_pdf_into_resumes
import requests 




app = Flask(__name__)
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
from records_api import records_bp
app.register_blueprint(records_bp)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-this")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

create_table()
create_test_invites_table()
create_employers_table()
create_jobs_table()
extend_resumes_table()

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

PASS_MARK = 2  # questions fully correct out of 3


def send_email(to_email, subject, body):
    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": os.getenv("BREVO_API_KEY"), "accept": "application/json"},
        json={"sender": {"email": EMAIL_ADDRESS, "name": "Hiring Team"},
              "to": [{"email": to_email}], "subject": subject, "textContent": body},
        timeout=15,
    )
    r.raise_for_status()
    
@app.route("/")
def home():
    if "employer_email" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))

@app.route("/upload")
def upload_form():
    if "employer_email" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", company_name=session.get("company_name"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        company_name = request.form.get("company_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not company_name or not email or not password:
            return render_template("signup.html", error="All fields are required.")

        if get_employer_by_email(email):
            return render_template("signup.html", error="An account with this email already exists.")

        password_hash = generate_password_hash(password)
        create_employer(company_name, email, password_hash)
        employer = get_employer_by_email(email)

        session["employer_id"] = employer["id"]
        session["employer_email"] = employer["email"]
        session["company_name"] = employer["company_name"]
        return redirect(url_for("dashboard"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        employer = get_employer_by_email(email)
        if not employer or not check_password_hash(employer["password_hash"], password):
            return render_template("login.html", error="Invalid email or password.")

        session["employer_id"] = employer["id"]
        session["employer_email"] = employer["email"]
        session["company_name"] = employer["company_name"]
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if "employer_email" not in session:
        return redirect(url_for("login"))
    jobs = get_jobs_for_employer(session["employer_id"])
    return render_template("dashboard.html", jobs=jobs, company_name=session.get("company_name"))


@app.route("/dashboard/jobs/<int:job_id>")
def job_detail(job_id):
    if "employer_email" not in session:
        return redirect(url_for("login"))

    job = get_job(job_id)
    if not job or job["employer_id"] != session["employer_id"]:
        return "Job not found.", 404

    results = get_resumes_for_job(job_id)

    strong_count = len([r for r in results if r.get("score", 0) >= 75])
    moderate_count = len([r for r in results if 50 <= r.get("score", 0) < 75])
    weak_count = len([r for r in results if r.get("score", 0) < 50])
    total_count = len(results)

    skill_distribution = defaultdict(list)
    for r in results:
        for m in r.get("matched_requirements", []):
            skill_distribution[m["requirement"]].append(r["filename"])
    skill_distribution = dict(skill_distribution)
    
    r1_results = get_round1_results(job_id)
    r1_passed = [r for r in r1_results if r["passed"]]

    return render_template(
        "index.html",
        job=job,
        results=results,
        total_count=total_count,
        strong_count=strong_count,
        moderate_count=moderate_count,
        weak_count=weak_count,
        skill_distribution=skill_distribution,
        company_name=session.get("company_name"),
        r1_results=r1_results,
        r1_passed=r1_passed
    )


@app.route("/dashboard/jobs/<int:job_id>/delete", methods=["POST"])
def delete_job_route(job_id):
    if "employer_email" not in session:
        return redirect(url_for("login"))

    job = get_job(job_id)
    if not job or job["employer_id"] != session["employer_id"]:
        return "Job not found.", 404

    delete_job(job_id, session["employer_id"])
    return redirect(url_for("dashboard"))

ALLOWED_EXT = (".pdf", ".docx")
MAX_RESUMES_PER_UPLOAD = 50

def collect_resume_units(files):
    """Turns uploads into (display_name, text) pairs. A PDF holding several
    resumes becomes several pairs. Non-PDF/DOCX files in a folder are skipped."""
    units, seen = [], {}

    def unique(name):
        seen[name] = seen.get(name, 0) + 1
        return name if seen[name] == 1 else f"{name} ({seen[name]})"

    for file in files:
        original = os.path.basename((file.filename or "").replace("\\", "/"))
        if not original or not original.lower().endswith(ALLOWED_EXT):
            continue
        save_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex[:8]}_{secure_filename(original)}")
        file.save(save_path)

        parts = []
        if original.lower().endswith(".pdf"):
            try:
                parts = split_pdf_into_resumes(save_path)
            except Exception as e:
                print("Split failed for", original, ":", e)
        print(f"{original}: found {max(len(parts), 1)} resume(s)")

        if len(parts) > 1:
            for n, (a, b, text) in enumerate(parts, 1):
                pages = f"p.{a}" if a == b else f"pp.{a}-{b}"
                units.append((unique(f"{original} - resume {n} ({pages})"), text))
        else:
            units.append((unique(original), extract_text(save_path)))
    return units

@app.route("/process", methods=["POST"])
def process():
    if "employer_email" not in session:
        return redirect(url_for("login"))

    role_title = request.form.get("role_title", "").strip() or "Untitled Role"
    jd_text = request.form.get("job_description", "").strip()
    files = request.files.getlist("resumes")

    if not jd_text or not files or all(f.filename == "" for f in files):
        return render_template("index.html", error="Make sure to upload at least one resume and paste a job description!")

    units = collect_resume_units(files)
    if not units:
        return render_template("index.html", error="No PDF or DOCX resumes were found in what you uploaded.")
    if len(units) > MAX_RESUMES_PER_UPLOAD:
        return render_template("index.html",
            error=f"That upload has {len(units)} resumes. Please upload at most {MAX_RESUMES_PER_UPLOAD} at a time.")

    job_id = create_job(session["employer_id"], role_title, jd_text)

    for display_name, resume_text in units:
        if not resume_text.strip():
            save_resume_result({
                "filename": display_name,
                "score": 0,
                "message": "Your file couldn't be read",
                "email": None,
                "name": None,
                "matched_requirements": [],
                "missing_requirements": [],
                "career_trajectory": {},
                "experience": {},
            }, job_id)
            continue

        result = parse_and_score(resume_text, jd_text)
        result["filename"] = display_name
        save_resume_result(result, job_id)
        time.sleep(2)

    return redirect(url_for("job_detail", job_id=job_id))

@app.route("/send_test_invites", methods=["POST"])
def send_test_invites():
    if "employer_id" not in session:                    
        return jsonify({"message": "Please log in."}), 401
    data = request.get_json()
    candidates = data.get("candidates", [])
    jd_text = data.get("jd_text", "")
    question_set_link = data.get("question_set_link", "").strip() or None
    
    job_id = data.get("job_id") or find_job_id_by_jd(session["employer_id"], jd_text)
    base_url = os.getenv("PUBLIC_BASE_URL") or request.host_url.rstrip("/")

    if not candidates:
        return jsonify({"message": "No candidates provided."}), 400

    sent, failed = [], []
    for c in candidates:
        token = str(uuid.uuid4())
        try:
            save_test_invite(token, c.get("filename"), c.get("email"), jd_text, question_set_link, job_id)
            test_link = f"{base_url}/test/{token}"
            body = (
                f"Hi,\n\nThank you for applying. As the next step, please complete "
                f"a short skills assessment for this role:\n\n{test_link}\n\n"
                f"Best,\nHiring Team"
            )
            send_email(c.get("email"), "Next step: Skills Assessment", body)
            sent.append(c.get("email"))
        except Exception as e:
             import traceback
             traceback.print_exc()
             print("Failed to send invite to", c.get("email"), ":", e)
             failed.append(c.get("email"))

    message = f"Sent {len(sent)} invite(s)."
    if failed:
        message += f" Failed for: {', '.join(failed)}."
    return jsonify({"message": message, "sent": sent, "failed": failed})


@app.route("/test/<token>")
def take_test(token):
    invite = get_test_invite(token)
    if not invite:
        return "This test link is invalid or has expired.", 404

    if invite.get("question_set_link"):
        return render_template("test_redirect.html", invite=invite)

    return app.send_static_file("assessment.html")

@app.get("/api/assessment/<token>/info")
def assessment_info(token):
    inv = get_test_invite(token)
    if not inv:
        return jsonify(ok=False, message="This test link is invalid or has expired."), 404
    if inv["status"] != "sent":
        return jsonify(ok=False, message="This test has already been started or completed."), 409
    return jsonify(ok=True, email=inv["email"])


@app.post("/api/assessment/<token>/start")
def assessment_start(token):
    d = request.get_json(silent=True) or {}
    name, phone = (d.get("name") or "").strip(), (d.get("phone") or "").strip()
    if not name or not phone:
        return jsonify(ok=False, message="Name and phone are required."), 400
    if not start_assessment(token, name, phone):
        return jsonify(ok=False, message="This test was already started."), 409
    return jsonify(ok=True)


@app.post("/api/assessment/<token>/violation")
def assessment_violation(token):
    d = request.get_json(silent=True) or {}
    row = record_violation(token, str(d.get("reason") or "unspecified")[:200])
    if not row:
        return jsonify(ok=False), 409
    return jsonify(ok=True, warnings=row[0], status=row[1])


@app.post("/api/assessment/<token>/submit")
def assessment_submit(token):
    d = request.get_json(silent=True) or {}
    reason = d.get("reason", "completed")
    details = d.get("details") if isinstance(d.get("details"), list) else []
    score = sum(1 for x in details if isinstance(x, dict) and x.get("ok"))
    quit_ = reason in ("quit_screen", "disqualified")
    passed = (not quit_) and score >= PASS_MARK
    status = "disqualified" if quit_ else "test_completed"
    save_assessment_result(token, score, passed, status, details)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(port=8000, debug=True)