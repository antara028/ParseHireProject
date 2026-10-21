"""Receives the proctored-test records from the assessment page."""
import os
import re
 
from flask import Blueprint, request, jsonify
from flask_cors import CORS
 
from records_db import create_records_table, save_full_record
 
records_bp = Blueprint("records", __name__, url_prefix="/api/records")
CORS(records_bp, origins=os.getenv("TEST_SITE_ORIGIN", "*"))
 
create_records_table()
 
EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")
 
 
def _json():
    return request.get_json(silent=True) or {}
 
 
@records_bp.post("/submit")
def submit():
    """Receives one finished test from the standalone assessment page."""
    d = _json()
    name = str(d.get("name") or "").strip()[:200]
    email = str(d.get("email") or "").strip().lower()[:200]
    phone = str(d.get("phone") or "").strip()[:50]
    if not name or not phone or not EMAIL_RE.match(email):
        return jsonify(ok=False, message="Invalid details."), 400
    answers = []
    for a in (d.get("answers") if isinstance(d.get("answers"), list) else [])[:10]:
        try:
            answers.append({"q": int(a.get("q")), "ok": bool(a.get("ok")),
                            "passed": int(a.get("passed", 0)), "total": int(a.get("total", 0)),
                            "code": str(a.get("code") or "")[:5000]})
        except (TypeError, ValueError, AttributeError):
            continue
    res = save_full_record(name, email, phone, answers, str(d.get("reason") or "completed"))
    if res is None:
        return jsonify(ok=False, message="A response from this email is already recorded."), 409
    return jsonify(ok=True)
 