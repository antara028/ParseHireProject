"""Separate 'assessment records' database for the proctored test."""
import os
import hmac
import json
import secrets
import time
 
import psycopg2
 
from database import get_connection as get_main_connection  # your existing resumes DB
 
PASS_MARK = 2      # questions fully correct (out of 3) needed to clear round 1
MAX_WARNINGS = 3
 
 
def get_records_connection():
    return psycopg2.connect(
        host=os.getenv("RECORDS_DB_HOST", "localhost"),
        database=os.getenv("RECORDS_DB_NAME", "assessment_records_db"),
        user=os.getenv("RECORDS_DB_USER", "postgres"),
        password=os.getenv("RECORDS_DB_PASSWORD", ""),
    )
 
 
def create_records_table():
    conn = get_records_connection()
    cur = conn.cursor()
    cur.execute("""
        create table if not exists assessment_records (
            id serial primary key,
            access_key text not null,
            name text,
            email text,
            phone text,
            status text default 'in_progress',   -- in_progress / completed / disqualified
            score integer,
            passed boolean default false,
            warnings integer default 0,
            violation_log jsonb default '[]'::jsonb,
            started_at timestamp default current_timestamp,
            completed_at timestamp
        );
    """)
    cur.execute("create index if not exists idx_ar_email on assessment_records (lower(email));")
    conn.commit()
    cur.close()
    conn.close()
 
 
# ---------- read side, used by the recruiter dashboard ----------
 
def get_resume_emails_for_job(job_id):
    conn = get_main_connection()
    cur = conn.cursor()
    cur.execute("select distinct lower(email) from resumes where job_id = %s and email is not null", (job_id,))
    emails = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return emails
 
 
def get_records_for_emails(emails):
    if not emails:
        return []
    conn = get_records_connection()
    cur = conn.cursor()
    cur.execute("""
        select name, email, phone, score, status, passed, warnings
        from assessment_records
        where lower(email) = any(%s)
        order by passed desc, score desc nulls last
    """, ([e.lower() for e in emails],))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"name": r[0], "email": r[1], "phone": r[2], "score": r[3],
             "status": r[4], "passed": bool(r[5]), "warnings": r[6]} for r in rows]
 
 
def count_passed_for_emails(emails):
    if not emails:
        return 0
    conn = get_records_connection()
    cur = conn.cursor()
    cur.execute("select count(*) from assessment_records where passed and lower(email) = any(%s)",
                ([e.lower() for e in emails],))
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n
 
 
def save_full_record(name, email, phone, answers, reason):
    """One-shot save used by the standalone assessment page.
    Returns (score, passed), or None if this email already has a record."""
    conn = get_records_connection()
    cur = conn.cursor()
    cur.execute("select 1 from assessment_records where lower(email) = lower(%s) limit 1", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return None
    seen, clean = set(), []
    for a in answers:
        if a["q"] not in seen:
            seen.add(a["q"])
            clean.append(a)
    score = sum(1 for a in clean if a.get("ok"))
    passed = reason in ("completed", "time_up") and score >= PASS_MARK
    cur.execute("""
        insert into assessment_records
            (access_key, name, email, phone, status, score, passed, completed_at)
        values ('direct', %s, %s, %s, 'completed', %s, %s, current_timestamp)
    """, (name, email, phone, score, passed))
    conn.commit()
    cur.close()
    conn.close()
    return score, passed
 