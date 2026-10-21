import re
#from sentence_transformers import SentenceTransformer , util
from dotenv import load_dotenv
from openai import OpenAI
import os 
import json 


                                             #skill ,certification and education using llm--

SYNONYM_MAP = {
    "llm": "large language model",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "js": "javascript",
    "ts": "typescript",
    "db": "database",
    "api": "application programming interface",
    "oop": "object oriented programming",
    "dl": "deep learning",
    "gan": "generative adversarial network",
}

def normalize_text(text):
    text_lower = text.lower()
    text_lower = text_lower.replace("-", " ")  # normalize hyphens to spaces
    for abbrev, full_form in SYNONYM_MAP.items():
        pattern = r'\b' + re.escape(abbrev) + r'\b'
        text_lower = re.sub(pattern, full_form, text_lower)
    return text_lower


EMAIL_REGEX = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

def extract_email(text):
    match = re.search(EMAIL_REGEX,text)
    if match:
        return match.group(0)
    else:
        return None
    
 
NAME_CUTOFF_PATTERN = re.compile(r'\b(course|email|mobile|phone|cgpa|address|linkedin|github)\b', re.IGNORECASE)

def extract_name(resume_text):
    junk_words = {"year", "course", "score", "board", "university",
                  "institute", "college", "class", "subject", "elective"}
    lines = [l.strip() for l in resume_text.split("\n") if l.strip()]
    for line in lines[:5]:
        cut = NAME_CUTOFF_PATTERN.search(line)
        candidate = line[:cut.start()] if cut else line
        candidate = re.split(r'[:@|]', candidate)[0]
        candidate = re.sub(r'\s{2,}', ' ', candidate).strip()

        if not candidate or "@" in candidate or re.search(r'\d', candidate):
            continue
        words = candidate.split()
        if not (1 < len(words) <= 4):
            continue
        if not all(w.replace(".", "").isalpha() and len(w.replace(".", "")) >= 2 for w in words):
            continue
        if any(w.lower() in junk_words for w in words):
            continue
        return candidate.title() if candidate.isupper() else candidate
    return None
 
#pre-trained model for embeddings   
#embedding_model = SentenceTransformer('all-MiniLM-L6-v2')

#cosine similarity
#def semantic_similarity(resume_text, jd_text):
 #   embedding_resume = embedding_model.encode(resume_text)
  #  embedding_jd = embedding_model.encode(jd_text)
   # similarity_score = util.cos_sim(embedding_resume, embedding_jd).item()
    #return round(similarity_score * 100, 1)
    
import numpy as np
from fastembed import TextEmbedding

_embedder = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")

def embed(texts):
    vecs = np.array(list(_embedder.embed(texts)))
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


load_dotenv()
openai_client = OpenAI(api_key=os.getenv("GROQ_API_KEY"),base_url="https://api.groq.com/openai/v1")
                                                         #openai client calling groq servers to provide the api access 

#helper func.
import time

def _call_llm_json(system_prompt, user_content, max_tokens=1500, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = openai_client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.0,
                max_tokens=max_tokens,
                extra_body={"reasoning_effort": "low", "reasoning_format": "hidden"},
            )
            content = response.choices[0].message.content
            return extract_json_from_response(content)
        except Exception as e:
            if "rate_limit" in str(e).lower() and attempt < max_retries - 1:
                print(f"Rate limited, waiting 15s (attempt {attempt+1})")
                time.sleep(15)
            else:
                raise

_jd_requirements_cache = {}
def extract_jd_requirements(jd_text):
    if jd_text in _jd_requirements_cache:
        return _jd_requirements_cache[jd_text]
    
    prompt = """
    Extract the concrete technical skills, tools, degree/education requirements,
    and certifications mentioned in this job description.

    CRITICAL RULES:
    - If items are listed as interchangeable alternatives using "or" (e.g. "Power BI, Tableau, or Streamlit"),
      group them as ONE requirement joined by " OR ".
    - If items are listed together as a required set (e.g. "Python (Pandas, NumPy, Scikit-Learn)"),
      extract EACH one as a SEPARATE, individual requirement: "Python", "Pandas", "NumPy", "Scikit-Learn".
      Do NOT bundle required sub-skills together - each must be checkable independently.

    Do NOT include generic phrases, soft skills, or filler words like "team",
    "experience", "similar", "cross-functional".

    Respond ONLY with a JSON array of short strings, nothing else.
    Example: ["SQL", "Python", "Pandas", "NumPy", "Scikit-Learn", "Power BI OR Tableau OR Streamlit"]
    """

    try:
       result = _call_llm_json(prompt, jd_text, max_tokens=1000)
       _jd_requirements_cache[jd_text] = result
       return result
    except Exception as e:
        print("Requirement extraction failed:", e)
        return []
    
def _chunk_resume_text(resume_text):
    raw_lines = [l.strip() for l in resume_text.split("\n") if l.strip()]
    chunks = []
    for line in raw_lines:
        parts = re.split(r'[•·;,|]', line)
        for part in parts:
            part = part.strip(" :-\t")
            if part:
                chunks.append(part)
    return list(dict.fromkeys(chunks))


def compare_sce(jd_text, resume_text, threshold=45):
    requirements = extract_jd_requirements(jd_text)
    chunks = _chunk_resume_text(resume_text)

    matched = []
    missing = []

    if not chunks:
        return {"matched": [], "missing": requirements}

    chunk_embeddings = embed(chunks)
    for req in requirements:
        alternatives = [a.strip() for a in req.split(" OR ")]

        best_alt = None
        best_score = 0

        for alt in alternatives:
            alt_norm = alt.lower().strip()
            exact_hit = any(alt_norm == c.lower() or alt_norm in c.lower() or c.lower() in alt_norm for c in chunks)
            if exact_hit:
                best_alt = alt
                best_score = 100.0
                break

            alt_embedding = embed([alt])
            scores = (alt_embedding @ chunk_embeddings.T)[0]
            alt_score = round(float(scores.max()) * 100, 1)
            if alt_score > best_score:
                best_score = alt_score
                best_alt = alt

        if best_score >= threshold:
            matched.append({"requirement": req, "matched_alternative": best_alt, "score": best_score})
        else:
            missing.append(req)

    return {"matched": matched, "missing": missing}

                                                 #career tarjectory using llm---
                                                 
                                                 
def extract_json_from_response(raw_text):
    print("RAW MODEL OUTPUT:", repr(raw_text))
    if not raw_text:
        raise ValueError("Empty response from model")
    cleaned = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip() #re.sub(pattern, replacement, string, flags)
    match = re.search(r'(\[.*\]|\{.*\})', cleaned, re.DOTALL)
                     #the pattern used to find json
    if not match:
        raise ValueError("No JSON found in response")
    return json.loads(match.group(1))
                                             
    
def analyze_career_trajectory(resume_text, jd_text):
    prompt = """
    You are analyzing a resume against a job description. Extract the person's
    work experience roles, in chronological order (oldest first). Assess whether
    the trajectory shows increasing seniority, and how well it aligns with the
    target role in the job description.

    Respond ONLY in this exact JSON format, nothing else:
    {
        "roles": ["Job Title 1", "Job Title 2"],
        "trend": "one sentence assessment",
        "trajectory_score": 75
    }
    trajectory_score must be an integer from 0 to 100.
    """

    try:
        return _call_llm_json(prompt, f"JOB DESCRIPTION:\n{jd_text}\n\nRESUME:\n{resume_text}", max_tokens=1200)
    except Exception as e:
        print("Trajectory analysis failed:", e)
        return {"trend": "Could not analyze.", "trajectory_score": 0, "roles": []}
    
    
                                                 #experience using llm---
                                                 
                                                 
                                                 
def format_months_as_years(total_months):
    years = total_months // 12
    months = total_months % 12

    if years == 0:
        return f"{months} month{'s' if months != 1 else ''}"
    elif months == 0:
        return f"{years} year{'s' if years != 1 else ''}"
    else:
        return f"{years} year{'s' if years != 1 else ''}, {months} month{'s' if months != 1 else ''}"
                                                    


def analyze_experience_duration(resume_text, jd_text):
    prompt = """
    You are analyzing a resume against a job description. First, determine if this
is an entry-level/internship role or a more senior role, based on the JD text.

Calculate total months of relevant professional experience from the resume's
date ranges (use today's date for "Present"). If this is an entry-level/internship
posting, having 0-6 months of relevant experience is EXCELLENT and should score
highly (80-100) - do not penalize students for not having years of experience
they wouldn't be expected to have.

Respond ONLY in this exact JSON format, nothing else:
{
    "total_months_experience": 18,
    "breakdown": ["Role 1: 6 months"],
    "experience_score": 80
}
experience_score must be an integer from 0 to 100.
    """

    try:
        result = _call_llm_json(prompt, f"JOB DESCRIPTION:\n{jd_text}\n\nRESUME:\n{resume_text}", max_tokens=1800)
        result["experience_display"] = format_months_as_years(result.get("total_months_experience", 0))
        return result
    except Exception as e:
        print("Experience analysis failed:", e)
        return {"total_months_experience": 0, "breakdown": [], "experience_score": 0, "experience_display": "0 months"}
    
def extract_contact_info_llm(resume_text):
    """LLM fallback for name/email extraction, used only when the fast
    regex/heuristic approach fails. Handles PDFs where pypdf's text
    extraction order doesn't match the visual page layout (multi-column
    resumes, boxed headers, etc.) - the LLM reads for meaning, so extraction
    order stops mattering."""
    prompt = """
    Extract the candidate's full name and email address from this resume text.
    The text may be jumbled out of visual order due to PDF extraction quirks -
    use context (e.g. "1st Year UG Student", degree info nearby) to identify
    the actual person's name, not a section header or table label.

    Respond ONLY in this exact JSON format, nothing else:
    {
        "name": "Full Name",
        "email": "email@example.com"
    }
    If either cannot be confidently found, use null for that field.
    """
    try:
        return _call_llm_json(prompt, resume_text, max_tokens=300)
    except Exception as e:
        print("Contact info extraction failed:", e)
        return {"name": None, "email": None}
    
    
    
def get_match_message(final_score, missing_sce):
    if final_score >= 75:
        return "Strong Match!"
    elif final_score >= 50:
        return "Moderate Match!"
    else:
        return "Sorry! Weak Match!"
    
    
def generate_test_questions(jd_text, num_questions=5):
    prompt = f"""
    You are creating a technical skills assessment for a candidate applying to
    this role. Generate {num_questions} interview-level questions appropriate
    for the role described, ranging from conceptual to practical.

    For each question, provide the question text, and a model/ideal answer
    that will be used to grade the candidate's response.

    Respond ONLY in this exact JSON format, nothing else:
    [
        {{"question": "...", "ideal_answer": "..."}},
        {{"question": "...", "ideal_answer": "..."}}
    ]
    """

    try:
        return _call_llm_json(prompt, jd_text, max_tokens=2000)
    except Exception as e:
        print("Question generation failed:", e)
        return []
    
    
def grade_test_submission(questions, answers_submitted):
    prompt = """
    You are grading a candidate's test submission. For each question, compare
    the candidate's answer to the ideal answer, and score it from 0-100 based
    on correctness and completeness.

    Respond ONLY in this exact JSON format, nothing else:
    {
        "per_question_scores": [85, 60, 90],
        "overall_score": 78,
        "feedback": "one sentence overall assessment"
    }
    """

    combined = json.dumps({"questions": questions, "candidate_answers": answers_submitted})

    try:
        return _call_llm_json(prompt, combined, max_tokens=1500)
    except Exception as e:
        print("Grading failed:", e)
        return {"per_question_scores": [], "overall_score": 0, "feedback": "Could not grade submission."}


def generate_candidate_summary(resume_text, jd_text):
    """A short, recruiter-facing summary of who this candidate is and their
    standout expertise, for quick scanning without reading the full resume."""
    prompt = """
    Write a brief, neutral 2-3 sentence summary of this candidate for a recruiter
    who is quickly scanning many resumes. Mention their core expertise, strongest
    relevant experience, and anything distinctive, in plain language. Do not
    repeat the job title or restate generic resume boilerplate. Do not use
    bullet points - write it as flowing sentences.

    Respond with ONLY the summary text, nothing else - no JSON, no quotes,
    no preamble.
    """
    try:
        response = openai_client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"JOB DESCRIPTION:\n{jd_text}\n\nRESUME:\n{resume_text}"}
            ],
            temperature=0.0,
            max_tokens=250,
            extra_body={"reasoning_effort": "low", "reasoning_format": "hidden"},
        )
        content = response.choices[0].message.content
        cleaned = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return cleaned if cleaned else "Summary unavailable."
    except Exception as e:
        print("Summary generation failed:", e)
        return "Summary unavailable."
    
    
        
def parse_and_score(resume_text, jd_text):
    email = extract_email(resume_text)
    llm_contact = extract_contact_info_llm(resume_text)
    name = llm_contact.get("name")
    email = email or llm_contact.get("email")
    
    summary = generate_candidate_summary(resume_text, jd_text)  
      
    resume_text_norm = normalize_text(resume_text)
    jd_text_norm = normalize_text(jd_text)

    sce_result = compare_sce(jd_text_norm, resume_text_norm)
    trajectory_result = analyze_career_trajectory(resume_text, jd_text)
    experience_result = analyze_experience_duration(resume_text, jd_text)

    total_requirements = len(sce_result["matched"]) + len(sce_result["missing"])
    requirement_score = round((len(sce_result["matched"]) / total_requirements) * 100, 1) if total_requirements > 0 else 0

    trajectory_score = trajectory_result.get("trajectory_score", 0)
    experience_score = experience_result.get("experience_score", 0)

    final_score = round(
    (requirement_score * 0.55) +
    (trajectory_score * 0.20) +
    (experience_score * 0.25),
    1
)

    missing_sce = sce_result["missing"]
    message = get_match_message(final_score, missing_sce)

    return {
        "email": email,
        "name" :  name,
        "score": final_score,
        "summary": summary,
        "matched_requirements": sce_result["matched"],
        "missing_requirements": sce_result["missing"],
        "career_trajectory": trajectory_result,
        "experience": experience_result,
        "message": message,
    }