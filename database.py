import os
import json
import time
import psycopg2
from dotenv import load_dotenv
load_dotenv()

def get_connection():
    url = os.getenv("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    return psycopg2.connect(
        host="localhost",
        database="resume_parser_database",
        user="postgres",
        password=os.getenv("DB_PASSWORD"),
    )

def create_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
         create table if not exists resumes (
            id serial primary key,
            filename text,
            email text,
            score float,
            message text,
            created_at timestamp default current_timestamp
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()
    




    
def create_test_invites_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        create table if not exists test_invites (
            id serial primary key,
            token text unique not null,
            filename text,
            email text,
            jd_text text,
            question_set_link text,
            status text default 'sent',
            created_at timestamp default current_timestamp
        );
    """)
    cursor.execute("""
        alter table test_invites add column if not exists question_set_link text;
    """)
    cursor.execute("alter table test_invites add column if not exists questions jsonb;")
    cursor.execute("alter table test_invites add column if not exists answers_submitted jsonb;")
    cursor.execute("alter table test_invites add column if not exists score float;")
    cursor.execute("alter table test_invites add column if not exists test_started_at timestamp;")
    cursor.execute("alter table test_invites add column if not exists test_completed_at timestamp;")
    cursor.execute("alter table test_invites add column if not exists job_id integer;")
    cursor.execute("alter table test_invites add column if not exists candidate_name text;")
    cursor.execute("alter table test_invites add column if not exists candidate_phone text;")
    cursor.execute("alter table test_invites add column if not exists passed boolean;")
    cursor.execute("alter table test_invites add column if not exists warnings integer default 0;")
    cursor.execute("alter table test_invites add column if not exists violation_log jsonb;")
    conn.commit()
    cursor.close()
    conn.close()


def save_test_invite(token, filename, email, jd_text, question_set_link=None, job_id=None):
    
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("""
        insert into test_invites (token, filename, email, jd_text, question_set_link, status, job_id)
        values (%s, %s, %s, %s, %s, 'sent', %s);
    """, (token, filename, email, jd_text, question_set_link, job_id))
    conn.commit(); cursor.close(); conn.close()


def get_test_invite(token):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "select token, filename, email, jd_text, question_set_link, status, questions, score from test_invites where token = %s",
        (token,)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return {
            "token": row[0], "filename": row[1], "email": row[2],
            "jd_text": row[3], "question_set_link": row[4], "status": row[5],
            "questions": row[6], "score": row[7]
        }
    return None


def save_test_questions(token, questions):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "update test_invites set questions = %s, test_started_at = current_timestamp where token = %s",
        (json.dumps(questions), token)
    )
    conn.commit()
    cursor.close()
    conn.close()



def save_test_questions(token, questions):
    """Saves the questions, starts the clock, and marks the test in progress."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """update test_invites
           set questions = %s, test_started_at = current_timestamp, status = 'in_progress'
           where token = %s and status = 'sent'""",
        (json.dumps(questions), token)
    )
    conn.commit()
    cursor.close()
    conn.close()


def record_violation(token, reason):
    """Adds one warning on the server; disqualifies at 3. Returns (warnings, status) or None."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        update test_invites
        set warnings = coalesce(warnings, 0) + 1,
            violation_log = coalesce(violation_log, '[]'::jsonb) || %s::jsonb,
            status = case when coalesce(warnings, 0) + 1 >= 3 then 'disqualified' else status end
        where token = %s and status = 'in_progress'
        returning warnings, status
    """, (json.dumps([{"reason": reason, "at": time.strftime("%Y-%m-%d %H:%M:%S")}]), token))
    row = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return row

def save_test_submission(token, answers_submitted, score):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        update test_invites
        set answers_submitted = %s, score = %s, status = 'test_completed', test_completed_at = current_timestamp
        where token = %s
    """, (json.dumps(answers_submitted), score, token))
    conn.commit()
    cursor.close()
    conn.close()
    
def create_employers_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        create table if not exists employers (
            id serial primary key,
            company_name text,
            email text unique not null,
            password_hash text not null,
            created_at timestamp default current_timestamp
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()


def create_employer(company_name, email, password_hash):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "insert into employers (company_name, email, password_hash) values (%s, %s, %s)",
        (company_name, email, password_hash)
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_employer_by_email(email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("select id, company_name, email, password_hash from employers where email = %s", (email,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return {"id": row[0], "company_name": row[1], "email": row[2], "password_hash": row[3]}
    return None

def create_jobs_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        create table if not exists jobs (
            id serial primary key,
            employer_id integer references employers(id),
            role_title text,
            jd_text text,
            created_at timestamp default current_timestamp
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()


def create_job(employer_id, role_title, jd_text):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "insert into jobs (employer_id, role_title, jd_text) values (%s, %s, %s) returning id",
        (employer_id, role_title, jd_text)
    )
    job_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return job_id


def get_jobs_for_employer(employer_id):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("""
        select j.id, j.role_title, j.created_at,
               count(r.id) as resume_count,
               count(*) filter (where r.score >= 75) as strong_count,
               count(*) filter (where r.score >= 50 and r.score < 75) as moderate_count,
               count(*) filter (where r.score < 50) as weak_count,
               (select count(*) from test_invites t where t.job_id = j.id and t.passed) as r1_passed
        from jobs j
        left join resumes r on r.job_id = j.id
        where j.employer_id = %s and j.created_at >= current_timestamp - interval '30 days'
        group by j.id
        order by j.created_at desc
    """, (employer_id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    return [{"id": r[0], "role_title": r[1], "created_at": r[2], "resume_count": r[3],
             "strong_count": r[4], "moderate_count": r[5], "weak_count": r[6], "r1_passed": r[7]}
            for r in rows]

def get_job(job_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("select id, employer_id, role_title, jd_text from jobs where id = %s", (job_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return {"id": row[0], "employer_id": row[1], "role_title": row[2], "jd_text": row[3]}
    return None


def extend_resumes_table():
    """Adds job_id and full-result columns to the existing resumes table
    without touching rows already there."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("alter table resumes add column if not exists job_id integer references jobs(id);")
    cursor.execute("alter table resumes add column if not exists name text;")
    cursor.execute("alter table resumes add column if not exists summary text;") 
    cursor.execute("alter table resumes add column if not exists matched_requirements jsonb;")
    cursor.execute("alter table resumes add column if not exists missing_requirements jsonb;")
    cursor.execute("alter table resumes add column if not exists career_trajectory jsonb;")
    cursor.execute("alter table resumes add column if not exists experience jsonb;")
    conn.commit()
    cursor.close()
    conn.close()


def save_resume_result(result, job_id):
    """Now stores the FULL result (not just filename/email/score/message) so a
    job's results can be reloaded later exactly as they first appeared."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        insert into resumes
            (job_id, filename, email, name, summary,  score, message,
             matched_requirements, missing_requirements, career_trajectory, experience)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """, (
        job_id,
        result.get("filename"),
        result.get("email"),
        result.get("name"),
        result.get("summary"),
        result.get("score"),
        result.get("message"),
        json.dumps(result.get("matched_requirements", [])),
        json.dumps(result.get("missing_requirements", [])),
        json.dumps(result.get("career_trajectory", {})),
        json.dumps(result.get("experience", {})),
    ))
    conn.commit()
    cursor.close()
    conn.close()


def get_resumes_for_job(job_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        select filename, email, name, summary, score, message,
               matched_requirements, missing_requirements, career_trajectory, experience
        from resumes where job_id = %s order by score desc
    """, (job_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [
        {
            "filename": row[0], "email": row[1], "name": row[2], "summary": row[3], "score": row[4],
            "message": row[5], "matched_requirements": row[6] or [],
            "missing_requirements": row[7] or [], "career_trajectory": row[8] or {},
            "experience": row[9] or {},
        }
        for row in rows
    ]
    
def delete_job(job_id, employer_id):
    """Deletes a job and all its resumes, scoped to the owning employer so
    one employer can never delete another's job by guessing an id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("delete from resumes where job_id = %s", (job_id,))
    cursor.execute("delete from jobs where id = %s and employer_id = %s", (job_id, employer_id))
    conn.commit()
    cursor.close()
    conn.close()
    
def find_job_id_by_jd(employer_id, jd_text):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("select id from jobs where employer_id=%s and jd_text=%s order by id desc limit 1",
                   (employer_id, jd_text))
    row = cursor.fetchone(); cursor.close(); conn.close()
    return row[0] if row else None


def start_assessment(token, name, phone):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("""
        update test_invites
        set candidate_name=%s, candidate_phone=%s, status='in_progress',
            test_started_at=current_timestamp, warnings=0
        where token=%s and status='sent'
    """, (name, phone, token))
    ok = cursor.rowcount > 0
    conn.commit(); cursor.close(); conn.close()
    return ok


def save_assessment_result(token, score, passed, status, details):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("""
        update test_invites
        set score=%s,
            passed = case when status='disqualified' then false else %s end,
            status = case when status='disqualified' then 'disqualified' else %s end,
            answers_submitted=%s, test_completed_at=current_timestamp
        where token=%s and status in ('in_progress','disqualified') and test_completed_at is null
    """, (score, passed, status, json.dumps(details), token))
    ok = cursor.rowcount > 0
    conn.commit(); cursor.close(); conn.close()
    return ok


def get_round1_results(job_id):
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("""
        select candidate_name, email, candidate_phone, score, status, passed, warnings
        from test_invites where job_id=%s and status <> 'sent'
        order by passed desc nulls last, score desc nulls last
    """, (job_id,))
    rows = cursor.fetchall(); cursor.close(); conn.close()
    return [{"name": r[0], "email": r[1], "phone": r[2], "score": r[3],
             "status": r[4], "passed": bool(r[5]), "warnings": r[6]} for r in rows]
    
    

if __name__ == "__main__":
    create_table()
    print("Table created successfully.")
    
