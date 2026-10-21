import re
from pypdf import PdfReader

EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

def split_pdf_into_resumes(path):
    """Returns [(first_page, last_page, text), ...], one entry per resume found in the PDF.
    A new resume starts on a page whose top lines contain an email that
    the current resume has not shown yet."""
    reader = PdfReader(path)
    groups = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        lines = [l for l in text.split("\n") if l.strip()]
        top_emails = {e.lower() for e in EMAIL_RE.findall("\n".join(lines[:15]))}
        all_emails = {e.lower() for e in EMAIL_RE.findall(text)}
        cur = groups[-1] if groups else None

        starts_new = cur is None or (top_emails and cur["emails"] and not (top_emails & cur["emails"]))
        if starts_new:
            groups.append({"start": i, "end": i, "texts": [text], "emails": set(all_emails)})
        else:
            cur["end"] = i
            cur["texts"].append(text)
            cur["emails"] |= all_emails
    return [(g["start"], g["end"], "\n".join(g["texts"]))
            for g in groups if "".join(g["texts"]).strip()]