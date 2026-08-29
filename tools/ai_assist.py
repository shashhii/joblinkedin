"""AI assistant for the LinkedIn application pipeline.

Provides three capabilities, backed by Gemini (Google AI Studio) or Grok (xAI):

  1. answer_question()   — answer Easy Apply screening questions that the
                           rule-based AUTO_ANSWERS table cannot resolve.
  2. monitor_workflow()  — analyze the marathon log/status and return a short
                           health summary + recommendations.
  3. tailor_resume()     — generate a job-specific ATS-friendly PDF using the
                           resume-generator project (resume.py --job "JD").

Provider selection:
  - Set GEMINI_API_KEY and/or GROK_API_KEY in tools/.ai.env (or the process
    environment). Gemini is preferred when both are present.
  - Optional: GEMINI_MODEL (default gemini-2.0-flash), GROK_MODEL
    (default grok-3-mini), AI_PROVIDER=gemini|grok to force one.

All calls are best-effort: on any error the functions return None/False so
the pipeline falls back to its rule-based behavior and never blocks.

CLI:
    python tools/ai_assist.py --verify          # test the API connection
    python tools/ai_assist.py --ask "question"  # one-off question test
    python tools/ai_assist.py --monitor         # one-off workflow health check
    python tools/ai_assist.py --resume "Python Developer @ Acme" -o out.pdf
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AI_ENV_FILE = HERE / ".ai.env"
AI_LOG = HERE / ".ai_log.txt"
RESUME_CACHE_DIR = HERE / ".ai_resumes"


def _resolve_resume_generator() -> Path:
    """Locate the resume-generator script portably.

    Resolution order:
      1. RESUME_GENERATOR_PATH env var (explicit override).
      2. tools/resume/resume.py (bundled in the repo for Render).
      3. The original Windows dev path (local machine fallback).
    """
    env = os.environ.get("RESUME_GENERATOR_PATH", "").strip()
    if env:
        return Path(env)
    bundled = HERE / "resume" / "resume.py"
    if bundled.exists():
        return bundled
    return Path(r"C:\Users\shash\Downloads\resume generator\resume.py")


RESUME_GENERATOR = _resolve_resume_generator()

GEMINI_MODEL_DEFAULT = "gemini-3.6-flash"
GROK_MODEL_DEFAULT = "grok-3-mini"
REQUEST_TIMEOUT = 45  # seconds; keep short so the pipeline never stalls

# Candidate profile used to ground the AI's answers (must stay consistent
# with the resume data and the rule-based AUTO_ANSWERS).
CANDIDATE_PROFILE = """
Candidate: Shashikumar S (Shashi Kumar)
- B.E. Computer Science & Engineering, Maharaja Institute of Technology, Mysore
  (Dec 2022 - May 2026), CGPA 7.9/10. Final-year student / fresher.
- Location: Mysore, Karnataka, India. Open to relocation and remote work.
- Email: shashikumar69440@gmail.com | Phone: +91 8431250682
- LinkedIn: linkedin.com/in/shashhii | Portfolio: https://shashhii.online
  | GitHub: github.com/shashhii | LeetCode: leetcode.com/u/shashi_0804
- Internships: App Development Intern @ MindMatrixEd (Android + Generative AI,
  Jan-Jun 2026); Web Development Intern @ TechnoHacks Solutions (HTML/CSS/JS,
  React.js, Node.js, REST APIs, Aug-Oct 2025).
- Skills: Python, C++, Java, JavaScript, React.js, Node.js, HTML/CSS, Android,
  SQL, Git, REST APIs, Machine Learning fundamentals, Generative AI.
- Work authorization: authorized to work in India, does NOT need visa
  sponsorship. Immediate joiner (0 days notice). Willing to relocate,
  work on-site, and work in shifts.
- Expected CTC: 3 LPA (fresher). Current CTC: 0.
""".strip()

ANSWER_RULES = """
Answer rules for job application screening questions:
1. Reply with ONLY the value to type/select — no explanations, no quotes.
2. Yes/No questions: answer Yes or No. Be positive about skills the candidate
   plausibly has from the profile (Python, Java, JavaScript, React, Node.js,
   SQL, Git, HTML/CSS, Android basics, ML/AI fundamentals). Answer No to
   visa sponsorship needs, master's degree, and multi-year professional
   experience claims beyond ~1 year of internships.
3. Years of experience questions: answer 1 (internship experience).
   If the question demands a minimum of 2+ years, still answer 1 honestly.
4. Numeric fields (notice period, joining days): 0. Expected salary/CTC:
   3 LPA or 300000 INR. Graduation year: 2026.
5. URL fields (portfolio/website/GitHub/LinkedIn): use the profile links above.
6. Free-text questions (e.g. "why this role", cover-letter style): write 2-3
   concise, genuine sentences as the candidate, first person, no fluff.
7. Never invent degrees, employers, or certifications not in the profile.
""".strip()


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        with AI_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_env() -> dict[str, str]:
    """Read KEY=VALUE pairs from tools/.ai.env (if present)."""
    env: dict[str, str] = {}
    if AI_ENV_FILE.exists():
        try:
            for raw in AI_ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
        except OSError:
            pass
    return env


def get_config() -> dict[str, str]:
    file_env = load_env()
    cfg = {
        "gemini_key": file_env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
        or os.environ.get("GOOGLE_API_KEY", ""),
        "grok_key": file_env.get("GROK_API_KEY") or os.environ.get("GROK_API_KEY", "")
        or os.environ.get("XAI_API_KEY", ""),
        "gemini_model": file_env.get("GEMINI_MODEL") or os.environ.get("GEMINI_MODEL", GEMINI_MODEL_DEFAULT),
        "grok_model": file_env.get("GROK_MODEL") or os.environ.get("GROK_MODEL", GROK_MODEL_DEFAULT),
        "provider": (file_env.get("AI_PROVIDER") or os.environ.get("AI_PROVIDER", "")).lower(),
    }
    return cfg


def provider() -> str:
    """Return 'gemini', 'grok', or '' when no key is configured."""
    cfg = get_config()
    forced = cfg["provider"]
    if forced == "gemini" and cfg["gemini_key"]:
        return "gemini"
    if forced == "grok" and cfg["grok_key"]:
        return "grok"
    if cfg["gemini_key"]:
        return "gemini"
    if cfg["grok_key"]:
        return "grok"
    return ""


def ai_available() -> bool:
    return provider() != ""


def _call_gemini(prompt: str, cfg: dict[str, str]) -> str:
    from google import genai  # google-genai SDK

    client = genai.Client(api_key=cfg["gemini_key"])
    response = client.models.generate_content(
        model=cfg["gemini_model"],
        contents=prompt,
        config={"temperature": 0.2, "max_output_tokens": 1024},
    )
    return (response.text or "").strip()


def _call_grok(prompt: str, cfg: dict[str, str]) -> str:
    from openai import OpenAI  # OpenAI-compatible xAI endpoint

    client = OpenAI(api_key=cfg["grok_key"], base_url="https://api.x.ai/v1",
                    timeout=REQUEST_TIMEOUT)
    response = client.chat.completions.create(
        model=cfg["grok_model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1024,
    )
    return (response.choices[0].message.content or "").strip()


def ask_ai(prompt: str) -> str | None:
    """Send a prompt to the configured provider. None on any failure."""
    which = provider()
    if not which:
        return None
    cfg = get_config()
    try:
        if which == "gemini":
            text = _call_gemini(prompt, cfg)
        else:
            text = _call_grok(prompt, cfg)
        if text:
            log(f"ai({which}) ok: {len(text)} chars")
            return text
        log(f"ai({which}) returned empty response")
    except Exception as exc:
        log(f"ai({which}) error: {exc.__class__.__name__}: {str(exc)[:200]}")
    return None


def clean_answer(text: str) -> str:
    """Strip markdown/quotes so the value can be typed into a form field."""
    text = text.strip()
    text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text, flags=re.I).strip()
    for ch in ('"', "'", "`", "*"):
        if len(text) > 1 and text.startswith(ch) and text.endswith(ch):
            text = text[1:-1].strip()
    return text.strip()


def answer_question(question: str, options: list[str] | None = None,
                    context: str = "") -> str | None:
    """Ask the AI to answer a screening question. Returns the value or None."""
    if not ai_available():
        return None
    parts = [
        CANDIDATE_PROFILE,
        ANSWER_RULES,
        "",
        f"Screening question from a job application form:\n{question.strip()}",
    ]
    if options:
        parts.append(f"Allowed options: {', '.join(options)}")
        parts.append("Pick exactly one of the allowed options if this is a "
                     "single-choice question.")
    if context:
        parts.append(f"Form context:\n{context[:800]}")
    answer = ask_ai("\n\n".join(parts))
    if answer is None:
        return None
    answer = clean_answer(answer)
    if options:
        # Prefer an exact option match (case-insensitive).
        lowered = {o.strip().lower(): o.strip() for o in options if o.strip()}
        if answer.lower() in lowered:
            return lowered[answer.lower()]
        for key, original in lowered.items():
            if key in answer.lower():
                return original
    return answer or None


def monitor_workflow(status_text: str, log_tail: str,
                     results_tail: str = "") -> str | None:
    """Analyze pipeline health and return a short summary + recommendations."""
    if not ai_available():
        return None
    prompt = "\n".join([
        "You are monitoring an autonomous LinkedIn job-application pipeline.",
        "It searches for fresh Easy Apply jobs hourly, filters entry-level dev",
        "roles, and applies headlessly. Target: 100 submissions.",
        "",
        f"Current status file:\n{status_text.strip()[:600]}",
        "",
        f"Recent marathon log:\n{log_tail.strip()[-3000:]}",
    ])
    if results_tail:
        prompt += f"\n\nRecent per-job results:\n{results_tail.strip()[-2000:]}"
    prompt += ("\n\nReply with a short health report (max 6 lines): "
               "1) progress & success rate, 2) the dominant failure cause, "
               "3) one concrete recommendation. Plain text, no markdown.")
    return ask_ai(prompt)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "job"


def tailor_resume(job_title: str, company: str = "", description: str = "",
                  timeout: int = 120) -> Path | None:
    """Generate a tailored PDF via the resume-generator project.

    Results are cached by normalized job title so repeated roles reuse the
    same PDF. Returns the PDF path, or None on failure.
    """
    if not RESUME_GENERATOR.exists():
        log(f"resume generator not found: {RESUME_GENERATOR}")
        return None
    try:
        RESUME_CACHE_DIR.mkdir(exist_ok=True)
    except OSError:
        return None

    cache_key = _slug(f"{job_title} {company}".strip())
    cached = RESUME_CACHE_DIR / f"{cache_key}.pdf"
    if cached.exists() and cached.stat().st_size > 1000:
        return cached

    jd = f"Role: {job_title}"
    if company:
        jd += f" at {company}"
    if description:
        jd += f"\n\n{description[:2500]}"

    try:
        proc = subprocess.run(
            [sys.executable, str(RESUME_GENERATOR), "--job", jd,
             "-o", str(cached)],
            cwd=str(RESUME_GENERATOR.parent),
            timeout=timeout, capture_output=True, text=True,
        )
        if cached.exists() and cached.stat().st_size > 1000:
            log(f"tailored resume generated: {cached.name}")
            return cached
        log(f"resume generation failed (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '')[:200]}")
    except subprocess.TimeoutExpired:
        log("resume generation timed out")
    except Exception as exc:
        log(f"resume generation error: {exc.__class__.__name__}")
    return None


def main() -> int:
    if "--verify" in sys.argv:
        which = provider()
        if not which:
            print("NO PROVIDER: set GEMINI_API_KEY or GROK_API_KEY in tools/.ai.env")
            return 1
        print(f"provider: {which}")
        cfg = get_config()
        print(f"model: {cfg['gemini_model'] if which == 'gemini' else cfg['grok_model']}")
        reply = ask_ai("Reply with exactly: AI_OK")
        if reply and "AI_OK" in reply.upper():
            print(f"API VERIFIED: {reply[:80]}")
            return 0
        print(f"API CHECK FAILED (reply: {str(reply)[:120]})")
        return 1

    if "--ask" in sys.argv:
        idx = sys.argv.index("--ask")
        question = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        options = None
        if "--options" in sys.argv:
            oidx = sys.argv.index("--options")
            if oidx + 1 < len(sys.argv):
                options = [o.strip() for o in sys.argv[oidx + 1].split(",")]
        answer = answer_question(question, options)
        print(json.dumps({"question": question, "answer": answer}, indent=2))
        return 0 if answer else 1

    if "--monitor" in sys.argv:
        status_text = ""
        log_tail = ""
        status_file = HERE / ".marathon_status.txt"
        marathon_log = HERE / ".marathon_log.txt"
        if status_file.exists():
            status_text = status_file.read_text(encoding="utf-8")
        if marathon_log.exists():
            log_tail = marathon_log.read_text(encoding="utf-8")[-3000:]
        report = monitor_workflow(status_text, log_tail)
        print(report or "AI unavailable or error")
        return 0 if report else 1

    if "--resume" in sys.argv:
        idx = sys.argv.index("--resume")
        spec = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "Software Developer"
        title, _, company = spec.partition("@")
        out = tailor_resume(title.strip(), company.strip())
        print(str(out) if out else "resume generation failed")
        return 0 if out else 1

    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
