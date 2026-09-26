"""LLM-Powered Job Match Filter & Scoring Gate.

Evaluates job listings against the master candidate profile (career-ops/cv.md)
to determine relevance, calculate compatibility score (0-100), and extract
tailored keyword highlights before applying.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
CV_PATH = PROJECT_ROOT / "career-ops" / "cv.md"

# Minimum score required to proceed with an application (0-100)
MIN_MATCH_SCORE = 60

# Load Candidate Master CV
def get_master_cv() -> str:
    """Read the master CV markdown file."""
    if CV_PATH.exists():
        return CV_PATH.read_text(encoding="utf-8")
    return """# Shashi Kumar
Mysore, Karnataka, India · shashikumar69440@gmail.com
B.E. Computer Science & Engineering (Dec 2022 - Mar 2026), VTU.
Skills: Python, Java, C++, JavaScript, TypeScript, React.js, Node.js, Next.js, Flutter, Android, SQL, AWS, Azure, GCP, AI/ML, REST APIs, Git.
Experience: Android App Dev using Gen AI (MindMatrixEd), Web Dev Intern (TechnoHacks Solutions).
Projects: COD Object Detection, MERN Ecommerce App, AI Live Currency Converter.
"""

def fast_heuristic_score(title: str, company: str, description: str = "") -> dict:
    """Fast deterministic relevance evaluation when LLM is unavailable or for pre-filtering."""
    t_lower = title.lower()
    d_lower = (description or "").lower()
    full_text = f"{t_lower} {company.lower()} {d_lower}"

    # Hard disqualifiers (senior, non-tech, executive)
    disqualifiers = [
        "principal", "director", "architect", "head of", "vp ", "vice president",
        "staff engineer", "lead developer", "10+ years", "8+ years", "7+ years",
        "human resources", "recruiter", "talent acquisition", "sales executive",
        "accountant", "nursing", "medical doctor", "legal counsel", "civil engineer"
    ]
    for d in disqualifiers:
        if d in t_lower:
            return {
                "score": 20,
                "verdict": "SKIP",
                "matching_skills": [],
                "reasoning": f"Role contains senior/non-tech keyword: '{d}'"
            }

    # Technical skill keywords
    skills = [
        "python", "java", "c++", "javascript", "typescript", "react", "react.js",
        "node", "node.js", "next.js", "flutter", "android", "sql", "postgresql",
        "mongodb", "aws", "gcp", "azure", "docker", "ai", "ml", "machine learning",
        "deep learning", "nlp", "llm", "genai", "generative ai", "fastapi", "django",
        "spring", "spring boot", "html", "css", "tailwind", "git", "rest api"
    ]
    matched = [s for s in skills if s in full_text]

    # Role level scoring
    score = 50
    if any(k in t_lower for k in ("intern", "trainee", "entry", "fresher", "junior", "associate", "graduate")):
        score += 25
    if any(k in t_lower for k in ("software", "developer", "engineer", "data", "ai", "full stack", "backend", "frontend")):
        score += 15

    score += min(len(matched) * 3, 20)
    score = min(score, 95)

    verdict = "APPLY" if score >= MIN_MATCH_SCORE else "SKIP"
    return {
        "score": score,
        "verdict": verdict,
        "matching_skills": matched[:8],
        "reasoning": f"Matched {len(matched)} core tech skills with relevant role title"
    }


def evaluate_job_match(title: str, company: str = "", description: str = "") -> dict:
    """Evaluate job match score using AI LLM with heuristic fallback."""
    # Try LLM evaluation first
    try:
        import ai_assist
        if ai_assist.ai_available():
            cv = get_master_cv()
            prompt = f"""You are an ATS Job Match Evaluator. Compare the Candidate Profile with the Job Posting.

Candidate Profile:
{cv[:1800]}

Job Posting:
Title: {title}
Company: {company}
Description: {description[:1800]}

Evaluate compatibility. Respond ONLY with valid JSON in this exact structure:
{{
  "score": <number 0-100>,
  "verdict": "APPLY" or "SKIP",
  "matching_skills": ["skill1", "skill2"],
  "tailored_summary": "<1-2 sentence professional summary tailored to this job>",
  "reasoning": "<short 1-sentence reason>"
}}
"""
            raw = ai_assist.ask_ai(prompt)
            if raw:
                # Clean code blocks if present
                clean = re.sub(r"^```[a-z]*\s*", "", raw.strip(), flags=re.MULTILINE)
                clean = re.sub(r"```$", "", clean.strip(), flags=re.MULTILINE).strip()
                data = json.loads(clean)
                if "score" in data and "verdict" in data:
                    return data
    except Exception:
        pass

    # Deterministic fallback
    return fast_heuristic_score(title, company, description)


if __name__ == "__main__":
    test_title = "Junior Full Stack Python Developer"
    test_company = "Tech Innovations"
    test_desc = "Looking for a software engineer proficient in Python, React, and SQL. Freshers and graduates welcome."
    res = evaluate_job_match(test_title, test_company, test_desc)
    print("Test Evaluation Result:")
    print(json.dumps(res, indent=2))
