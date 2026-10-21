import os
from pypdf import PdfReader
from docx import Document 
import re 
import pdfplumber



def _looks_letter_spaced(text):
    """Detects pypdf's letter-spacing bug: some PDF font encodings extract
    with a space between every single character."""
    sample = text[:500]
    tokens = sample.split(' ')
    if len(tokens) < 10:
        return False
    single_char_tokens = sum(1 for t in tokens if len(t) == 1)
    return (single_char_tokens / len(tokens)) > 0.5


def _fix_letter_spacing(text):
    """Collapses letter-spaced text back into normal words.
    Assumes a run of 2+ spaces marks a real word boundary, while single
    spaces are the artificial per-letter gaps."""
    fixed_lines = []
    for line in text.split('\n'):
        if _looks_letter_spaced(line):
            words = re.split(r'\s{2,}', line)
            words = [w.replace(' ', '') for w in words]
            fixed_lines.append(' '.join(words))
        else:
            fixed_lines.append(line)
    return '\n'.join(fixed_lines)

def _extract_with_pdfplumber(file_path):
    """Fallback for PDFs pypdf can't parse (custom fonts, multi-column
    layouts, unusual encodings) - slower, but handles more edge cases."""
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


#read pdf
def extracting_text_from_pdf(file_path):
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text

    if not text.strip():
        print(f"pypdf got nothing for {file_path}, trying pdfplumber fallback...")
        text = _extract_with_pdfplumber(file_path)

    text = _fix_letter_spacing(text)
    return text


#read doc
def extracting_text_from_docx(file_path):
    doc = Document(file_path)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    text = _fix_letter_spacing(text)
    return text


def extract_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    
    try: #we used exception to avoid any corrupted file ...func crash.
    
        if ext == ".pdf":
            return extracting_text_from_pdf(file_path)
        elif ext == ".docx":
            return extracting_text_from_docx(file_path)
        else: 
            print("Unsupported file type : ",ext)
            return ""
        
    except Exception as e:
        print("Failed to read your file sryy", e)
        return ""
        
    
        