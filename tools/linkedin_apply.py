"""Apply to a LinkedIn Easy Apply job on the user's behalf.

Runs a VISIBLE browser reusing the logged-in profile (~/.linkedin-mcp/profile).
Built on the proven pattern from linkedin_fill_test.py:
  - direct page-level locators (no modal scoping abstraction)
  - click an input before filling it
  - get_by_role("button", name=...) for navigation
  - the "N/M pages" indicator as the progress signal

Flow per screen:
  1. Log the dialog text + fields.
  2. Fill visible empty contact inputs (phone/email/name).
  3. Upload the resume on the first screen that has a file input.
  4. Auto-answer resolvable screening questions (work auth = Yes, sponsorship = No,
     relocation = Yes); pause (NEED_INPUT) for anything else.
  5. Click Next/Continue/Review; on the review screen click Submit (with --submit).

Handshake files (inside tools/):
    .apply_status.txt   script -> assistant
    .apply_answer.txt   assistant -> script (answer to a pending question)
    .apply_log.txt      full step-by-step log
    .apply_debug/       screenshots

Usage:
    python tools/linkedin_apply.py <job-url> <resume.pdf> [--submit]
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

# Optional AI assistant (Gemini/Grok): answers questions the rule table cannot
# resolve and generates per-job tailored resumes. Degrades gracefully when no
# API key is configured.
try:
    import ai_assist
except Exception:
    ai_assist = None

HERE = Path(__file__).resolve().parent
STATUS_FILE = HERE / ".apply_status.txt"
ANSWER_FILE = HERE / ".apply_answer.txt"
LOG_FILE = HERE / ".apply_log.txt"
DEBUG_DIR = HERE / ".apply_debug"
BATCH_RESULTS_FILE = HERE / ".batch_results.txt"
PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"

# Chromium launch flags. The --no-sandbox / --disable-dev-shm-usage /
# --disable-gpu trio is required for headless Chromium on Render (Linux,
# 512MB, running as root); they are harmless no-ops on local Windows.
BROWSER_ARGS = [
    "--start-maximized",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--no-first-run",
    "--no-default-browser-check",
    # --- Memory savers (Render free tier = 512MB, shared with Flask + marathon) ---
    # Cap the V8 heap per renderer; this is the single biggest lever.
    "--js-flags=--max-old-space-size=192",
    # Disable heavy/unnecessary features that allocate memory.
    "--disable-features=Translate,OptimizationHints,InterestFeedContentSuggestions,"
    "PrivacySandboxSettings4,ThirdPartyStoragePartitioning,VizDisplayCompositor,"
    "PaintHolding,MediaRouter,AudioService",
    "--disable-background-networking",
    "--disable-component-update",
    "--mute-audio",
    "--disable-logging",
    "--disable-breakpad",
    "--disable-crash-reporter",
    "--disable-hang-monitor",
    "--disable-notifications",
    "--disable-sync",
]


def _inject_session(context) -> None:
    """Best-effort: inject LinkedIn cookies from tools/.session/cookies.json.

    On Render the persistent profile is empty, so the login comes from the
    R2-restored cookie file. Locally the profile already holds the session and
    this is a harmless refresh. Never raises.
    """
    try:
        import r2_sync
        cookies = r2_sync.load_cookies()
        if cookies:
            context.add_cookies(cookies)
            log(f"injected {len(cookies)} session cookies")
    except Exception as exc:
        log(f"cookie inject skipped: {exc.__class__.__name__}")

CANDIDATE = {
    "first_name": "Shashi",
    "last_name": "Kumar",
    "email": "shashikumar69440@gmail.com",
    # Local number only: the Easy Apply country-code select already holds India (+91).
    "phone": "8431250682",
}

AUTO_ANSWERS = [
    (("legally authorized", "authorised to work", "right to work", "work authorization",
      "authorized to work", "work in india"), "Yes"),
    (("require sponsorship", "need sponsorship", "visa sponsorship", "sponsor"), "No"),
    (("willing to relocate", "open to relocation", "relocate"), "Yes"),
    (("onsite setting", "work in an onsite", "work on-site", "work from office",
      "commuting", "commute"), "Yes"),
    # Experience questions: user instructed to answer "1".
    (("years of work experience", "years of experience", "how many years",
      "experience do you have", "total experience", "overall experience",
      "relevant experience", "experience in years", "experience as"), "1"),
    # Education questions.
    (("bachelor's degree", "bachelors degree", "bachelor degree",
      "undergraduate degree"), "Yes"),
    (("master's degree", "masters degree", "postgraduate"), "No"),
    # Availability / notice period: immediate joiner = 0 days.
    (("available to start", "start date", "join immediately",
      "immediately available"), "Yes"),
    (("notice period",), "0"),
    # Year of graduation / pass-out.
    (("year of graduation", "year of passing", "pass out", "passout",
      "graduation year", "expected graduation", "year of completion"), "2026"),
    # "Which year of your degree are you currently pursuing?" — graduated.
    (("which year of your degree", "year of your degree",
      "currently pursuing"), "Completed"),
    # CTC in LPA (lakhs per annum) — fresher: current 0, expected 3 LPA.
    (("current ctc(lpa)", "current ctc (lpa)", "current salary (lpa)",
      "current compensation (lpa)"), "0"),
    (("expected ctc(lpa)", "expected ctc (lpa)", "expected salary (lpa)",
      "expected compensation (lpa)", "ctc(lpa)", "ctc (lpa)", "in lpa"), "3"),
    # Current/expected CTC (absolute INR).
    (("current ctc", "current salary", "current compensation"), "0"),
    (("expected ctc", "expected salary", "salary expectation",
      "annual salary", "annual income", "annual ctc", "per annum"), "300000"),
    # Willing to work in shifts.
    (("willing to work", "shift", "rotational"), "Yes"),
    # Joining availability — numeric days expected by most forms.
    (("how soon", "join us", "start working", "when can you start",
      "earliest you can", "notice period in days", "joining time"), "0"),
    # Self-rating questions ("Rate yourself in X out of 10") -> 7.
    # Must come before the "unpaid" rule: both can appear in one label blob.
    (("rate yourself", "rate your", "out of 10", "out of 5", "out of 100",
      "on a scale of"), "7"),
    # Unpaid-internship consent questions: answer Yes to keep the pipeline
    # moving (an application is not a contract; user can decline later).
    (("unpaid",), "Yes"),
    # Consent / assessment / background-check style questions.
    (("consent", "agree", "acknowledge", "background check", "assessment",
      "willing to complete", "complete a task"), "Yes"),
    # "Have you completed the full application at <external site>?" -> No.
    (("completed the full application", "completed an application",
      "applied on", "application at", "applied through"), "No"),
    # LinkedIn profile / portfolio / website URLs.
    (("linkedin profile", "linkedin url", "linkedin link"),
     "https://www.linkedin.com/in/shashhii"),
    (("portfolio", "personal website", "website url", "website link",
      "github", "online profile", "profile url", "profile link",
      "link to your", "url of your", "your website"), "https://shashhii.online"),
    # Career / employment breaks: none.
    (("career break", "career gap", "employment gap"), "No"),
    # Generic yes/no skill & experience questions (radio groups and text).
    # Keep LAST so the specific rules above get the first match.
    (("do you have experience", "do you have hands-on", "experience with",
      "have you worked with", "have you used", "do you have knowledge",
      "do you possess", "are you comfortable", "are you proficient",
      "familiar with", "do you know", "have you completed", "can you work",
      "are you willing", "are you able", "willingness", "worked on"), "Yes"),
]

log_lines: list[str] = []

# When True (set via --autonomous), never wait for a human answer: unresolvable
# questions fail fast so an unattended pipeline can move on to the next job.
AUTONOMOUS = False


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    log_lines.append(line)
    try:
        LOG_FILE.write_text("\n".join(log_lines), encoding="utf-8")
    except OSError:
        pass
    print(f"[apply] {msg}", flush=True)


LAST_STATUS = ""


def status(msg: str) -> None:
    global LAST_STATUS
    LAST_STATUS = msg
    STATUS_FILE.write_text(msg, encoding="utf-8")
    log(f"STATUS: {msg}")


def snap(page, name: str) -> None:
    # In autonomous mode skip routine screenshots (slow); keep failure shots.
    if AUTONOMOUS and not name.startswith(("02", "25", "30")):
        return
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=False)
    except Exception:
        pass


def wait_for_answer(timeout_seconds: int = 600) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            if ANSWER_FILE.exists():
                text = ANSWER_FILE.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except OSError:
            pass
        time.sleep(1)
    return ""


def dialog_text(page, limit: int = 300) -> str:
    try:
        return page.evaluate(
            "() => { const m = document.querySelector('dialog, .jobs-easy-apply-modal, div[role=\"dialog\"]'); "
            "return m ? (m.innerText || '') : 'NO-MODAL'; }"
        )[:limit].replace("\n", " | ")
    except Exception:
        return "EVAL-ERROR"


def page_indicator(text: str) -> str:
    """Extract the 'N/M pages' progress marker from the dialog text."""
    import re
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*pages?", text)
    return m.group(0) if m else ""


def fill_visible_inputs(page) -> None:
    """Fill every visible empty contact input on the current screen."""
    # Phone (tel inputs).
    tels = page.locator("input[type='tel']")
    for i in range(tels.count()):
        loc = tels.nth(i)
        try:
            if loc.is_visible(timeout=300) and not loc.input_value():
                loc.click(timeout=1500)
                loc.fill(CANDIDATE["phone"])
                log(f"filled tel[{i}] with phone")
        except Exception as exc:
            log(f"tel[{i}] fill error: {exc.__class__.__name__}")

    # Email inputs/selects.
    emails = page.locator("input[type='email'], input[name*='email' i]")
    for i in range(emails.count()):
        loc = emails.nth(i)
        try:
            if loc.is_visible(timeout=300) and not loc.input_value():
                loc.click(timeout=1500)
                loc.fill(CANDIDATE["email"])
                log(f"filled email[{i}]")
        except Exception as exc:
            log(f"email[{i}] fill error: {exc.__class__.__name__}")

    # First/last name inputs.
    for selector, value in [
        ("input[name*='firstName' i], #firstName", CANDIDATE["first_name"]),
        ("input[name*='lastName' i], #lastName", CANDIDATE["last_name"]),
    ]:
        locs = page.locator(selector)
        for i in range(locs.count()):
            loc = locs.nth(i)
            try:
                if loc.is_visible(timeout=300) and not loc.input_value():
                    loc.click(timeout=1500)
                    loc.fill(value)
                    log(f"filled name input ({selector})")
            except Exception:
                continue


def upload_resume(page, resume_path: Path) -> bool:
    """Upload the tailored resume. Clicks 'Upload resume' first if LinkedIn
    hides the file input behind that button (saved-resume screen)."""
    try:
        # If a saved resume is pre-selected, switch to the upload flow.
        for btn_text in ["Upload resume", "Upload Resume", "Upload"]:
            try:
                btn = page.get_by_role("button", name=btn_text).first
                if btn.is_visible(timeout=800):
                    btn.click()
                    log(f"clicked '{btn_text}' button")
                    time.sleep(1.5)
                    break
            except Exception:
                continue
        file_input = page.locator("input[type='file']").first
        if file_input.count() == 0:
            return False
        file_input.set_input_files(str(resume_path))
        time.sleep(2.5)
        log(f"uploaded resume: {resume_path.name}")
        return True
    except Exception as exc:
        log(f"resume upload error: {exc.__class__.__name__}")
        return False


def resolve_question(question_text: str):
    q = question_text.lower()
    for keys, answer in AUTO_ANSWERS:
        if any(k in q for k in keys):
            return answer
    return None


def handle_screen_questions(page) -> bool:
    """Answer screening questions on this screen. Returns False if stuck."""
    # Text/number/textarea inputs that are empty + visible.
    inputs = page.locator("input[type='text'], input[type='number'], textarea")
    for i in range(inputs.count()):
        inp = inputs.nth(i)
        try:
            if not inp.is_visible(timeout=300) or inp.input_value():
                continue
            # Find the question label: prefer the closest form-element container
            # (each question lives in its own wrapper); fall back to walking up
            # until text containing '?' or '!' is found; finally use the
            # placeholder / aria-label attributes.
            label_text = ""
            is_required = False
            try:
                label_text, is_required = inp.evaluate(
                    """el => {
                      const wrap = el.closest('.jobs-easy-apply-form-element, fieldset, .artdeco-text-input');
                      let required = el.required === true || el.getAttribute('aria-required') === 'true';
                      if (wrap) {
                        const t = wrap.innerText || '';
                        if (t.includes('*')) required = true;
                        if (t && t.length < 400) return [t, required];
                      }
                      let n = el.parentElement;
                      for (let d = 0; d < 6 && n; d++) {
                        const t = n.innerText || '';
                        if ((t.includes('?') || t.includes('!')) && t.length < 400) return [t, required];
                        n = n.parentElement;
                      }
                      const ph = el.getAttribute('placeholder') || el.getAttribute('aria-label') || '';
                      return [ph, required];
                    }"""
                )
            except Exception:
                pass
            auto = resolve_question(label_text)
            if auto is None and ai_assist is not None and label_text.strip():
                # AI fallback for questions the rule table cannot resolve.
                try:
                    ai_answer = ai_assist.answer_question(label_text)
                    if ai_answer:
                        auto = ai_answer
                        log(f"ai-answered text question: {label_text.strip()[:60]!r} -> {auto[:60]!r}")
                except Exception as exc:
                    log(f"ai answer error: {exc.__class__.__name__}")
            if auto is not None:
                inp.click(timeout=1500)
                inp.fill(str(auto))
                log(f"auto-answered text question: {label_text.strip()[:60]!r} -> {auto}")
                continue
            if AUTONOMOUS:
                # Optional field with no recognizable label: skip it and try to
                # advance; validation will tell us if it was actually required.
                if not is_required and not label_text.strip():
                    log("autonomous: skipping unlabeled optional field")
                    continue
                status(f"FAILED:unresolvable-question:{label_text.strip()[:120]}")
                log(f"autonomous: skipping unresolvable question: {label_text.strip()[:80]!r}")
                return False
            status(f"NEED_INPUT:{label_text.strip()[:200]}")
            answer = wait_for_answer()
            if answer:
                inp.click(timeout=1500)
                inp.fill(answer)
                try:
                    ANSWER_FILE.unlink()
                except OSError:
                    pass
                log(f"user answered: {answer[:60]!r}")
            else:
                status("FAILED:unanswered-question")
                return False
        except Exception as exc:
            log(f"question handling error: {exc.__class__.__name__}")
            continue

    # Radio groups (yes/no screening). LinkedIn uses div[role="radio"] with
    # aria-label inside fieldset[role="radiogroup"]. Question text is in a <p>
    # before the fieldset.
    try:
        radio_groups = page.evaluate(
            """() => {
              const results = [];
              document.querySelectorAll('fieldset[role="radiogroup"], fieldset').forEach((fs, fi) => {
                const radios = fs.querySelectorAll('[role="radio"]');
                if (radios.length < 2) return;
                // Question text, tried in order: legend, form-element wrapper
                // <p>, preceding siblings, parent's <p>.
                let q = '';
                const legend = fs.querySelector('legend');
                if (legend) q = (legend.innerText || '').trim();
                if (!q) {
                  const wrap = fs.closest('.jobs-easy-apply-form-element');
                  if (wrap) {
                    const p = wrap.querySelector('p');
                    if (p) q = (p.innerText || '').trim();
                  }
                }
                if (!q) {
                  let prev = fs.previousElementSibling;
                  for (let d = 0; d < 3 && prev && !q; d++) {
                    const t = (prev.innerText || '').trim();
                    if (t && t.length < 300 && !t.includes('\\n')) q = t;
                    prev = prev.previousElementSibling;
                  }
                }
                if (!q) {
                  const parent = fs.parentElement;
                  if (parent) {
                    const p = parent.querySelector('p');
                    if (p) q = (p.innerText || '').trim();
                  }
                }
                const options = [];
                radios.forEach((r, ri) => {
                  options.push({
                    ri,
                    label: r.getAttribute('aria-label') || (r.innerText || '').trim(),
                    checked: r.getAttribute('aria-checked') === 'true',
                  });
                });
                results.push({ fi, question: q.slice(0, 200), options });
              });
              return results;
            }"""
        )
    except Exception:
        radio_groups = []

    for group in radio_groups:
        q_text = group.get("question", "")
        auto = resolve_question(q_text)
        option_labels = [o.get("label", "").strip() for o in group.get("options", [])]
        if auto is None and q_text.strip() and ai_assist is not None:
            # AI fallback: pick the right option for unknown radio questions.
            try:
                ai_answer = ai_assist.answer_question(q_text, option_labels)
                if ai_answer:
                    auto = ai_answer
                    log(f"ai-answered radio: {q_text.strip()[:60]!r} -> {auto}")
            except Exception as exc:
                log(f"ai radio answer error: {exc.__class__.__name__}")
        if auto is None and AUTONOMOUS:
            # Fallback: unknown yes/no question -> answer "Yes" and move on.
            labels = {o.get("label", "").strip().lower() for o in group.get("options", [])}
            if "yes" in labels and "no" in labels:
                auto = "Yes"
                log(f"autonomous guess for radio: {q_text.strip()[:60]!r} -> Yes")
        if auto is None:
            continue
        # Find the option whose aria-label matches the answer.
        target = None
        for opt in group.get("options", []):
            if opt.get("checked"):
                break
            if opt.get("label", "").strip().lower() == auto.lower():
                target = opt
                break
        if target is None:
            continue
        try:
            fs_loc = page.locator("fieldset[role='radiogroup'], fieldset").nth(group["fi"])
            radio_loc = fs_loc.locator("[role='radio']").nth(target["ri"])
            radio_loc.click(force=True)
            time.sleep(0.5)
            log(f"auto-answered radio: {q_text.strip()[:60]!r} -> {auto}")
        except Exception as exc:
            log(f"radio click error: {exc.__class__.__name__}")

    # Dropdown selects for yes/no style questions.
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        try:
            if not sel.is_visible(timeout=300):
                continue
            label_text = sel.evaluate(
                "el => { let n = el.closest('.jobs-easy-apply-form-element, fieldset, div'); "
                "return n ? (n.innerText || '') : ''; }"
            )
            # Skip the phone country-code select (contains country names).
            if "(+91)" in label_text or "country code" in label_text.lower():
                continue
            auto = resolve_question(label_text)
            if auto is None:
                continue
            # Pick the option whose text matches the answer.
            options = sel.locator("option")
            for j in range(options.count()):
                opt_text = (options.nth(j).inner_text() or "").strip()
                if opt_text.lower() == auto.lower():
                    sel.select_option(index=j)
                    log(f"auto-selected option: {label_text.strip()[:60]!r} -> {opt_text}")
                    break
        except Exception:
            continue

    return True


def read_validation_errors(page) -> str:
    parts = []
    try:
        text = dialog_text(page, limit=2000)
        for marker in ["enter a valid", "is required", "please answer", "required", "invalid"]:
            idx = text.lower().find(marker)
            if idx >= 0:
                parts.append(text[max(0, idx - 60): idx + 80].strip())
    except Exception:
        pass
    return " | ".join(dict.fromkeys(parts))[:300]


def cleanup_modal(page) -> None:
    """Close any leftover Easy Apply modal so the next job starts clean."""
    try:
        done_btn = page.get_by_role("button", name="Done").first
        if done_btn.is_visible(timeout=800):
            done_btn.click()
            time.sleep(0.5)
            return
    except Exception:
        pass
    try:
        dismiss = page.locator("button[aria-label='Dismiss']").first
        if dismiss.is_visible(timeout=800):
            dismiss.click()
            time.sleep(0.8)
            discard = page.get_by_role("button", name="Discard").first
            if discard.is_visible(timeout=1200):
                discard.click()
                time.sleep(0.8)
    except Exception:
        pass


def apply_to_job(page, job_url: str, resume_path: Path, do_submit: bool) -> str:
    """Apply to one job on an already-open page. Returns the final status."""
    try:
        page.goto(job_url, wait_until="domcontentloaded", timeout=45_000)
    except Exception:
        return "FAILED:page-load-timeout"
    time.sleep(2.5)
    log(f"loaded: {page.url}")
    # Session-expiry detection: LinkedIn bounces logged-out users to the
    # authwall. Fail fast with a distinct status so the marathon can stop
    # applying and alert the operator instead of burning the whole batch.
    if "authwall" in page.url or "/login" in page.url:
        snap(page, "00-authwall")
        return "FAILED:session-expired"
    snap(page, "01-job-page")

    # Per-job tailored resume: extract the job title/company from the page and
    # generate a tailored PDF via the resume-generator project (cached). Falls
    # back to the default resume on any failure.
    if ai_assist is not None:
        try:
            title = ""
            company = ""
            try:
                title = page.locator("h1").first.inner_text(timeout=3000).strip()
            except Exception:
                pass
            try:
                company = page.locator(
                    ".job-details-jobs-unified-top-card__company-name, "
                    ".jobs-unified-top-card__company-name, "
                    "[data-test-id='topcard-org-name']"
                ).first.inner_text(timeout=2000).strip()
            except Exception:
                pass
            if title:
                tailored = ai_assist.tailor_resume(title, company)
                if tailored is not None:
                    resume_path = tailored
                    log(f"using tailored resume: {tailored.name}")
        except Exception as exc:
            log(f"tailored resume error: {exc.__class__.__name__}")

    # LinkedIn renders Easy Apply as either a <button> or an <a> element
    # (aria-label="Easy Apply to this job"), depending on the page variant.
    easy = page.locator(
        "button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], "
        "a:has-text('Easy Apply'), a[aria-label*='Easy Apply'], .jobs-apply-button"
    ).first
    try:
        easy.wait_for(state="visible", timeout=12_000)
        easy.click()
    except Exception:
        snap(page, "02-no-easy-apply")
        status("FAILED:no-easy-apply-button")
        return LAST_STATUS
    log("clicked Easy Apply")

    # Wait for the modal content to actually render (poll up to ~15s).
    modal_ready = False
    for _ in range(30):
        time.sleep(0.5)
        t = dialog_text(page, limit=500)
        if "pages" in t or "Contact info" in t or "Resume" in t:
            modal_ready = True
            break
    if not modal_ready:
        # Retry clicking Easy Apply once.
        try:
            easy.click()
            log("re-clicked Easy Apply")
            for _ in range(20):
                time.sleep(0.5)
                t = dialog_text(page, limit=500)
                if "pages" in t or "Contact info" in t or "Resume" in t:
                    modal_ready = True
                    break
        except Exception:
            pass
    if not modal_ready:
        snap(page, "02-modal-not-rendered")
        status("FAILED:modal-did-not-render")
        return LAST_STATUS
    time.sleep(1)
    snap(page, "03-modal-open")

    resume_uploaded = False
    same_screen_count = 0
    final_status = "FAILED:incomplete"

    for step in range(16):
        text = dialog_text(page, limit=2000)
        indicator = page_indicator(text)
        log(f"--- screen {step} ({indicator or 'no-indicator'}): {text[:150]}")
        snap(page, f"10-screen-{step}")

        if "NO-MODAL" in text:
            # Modal gone: either submitted/closed or between screens.
            time.sleep(1.5)
            text2 = dialog_text(page, limit=300)
            if "NO-MODAL" in text2:
                if "applied" in page.content().lower()[:20000]:
                    final_status = "DONE:submitted"
                else:
                    final_status = "DONE:modal-closed"
                status(final_status)
                snap(page, "20-modal-gone")
                break
            continue

        fill_visible_inputs(page)
        if not resume_uploaded:
            if upload_resume(page, resume_path):
                resume_uploaded = True

        if not handle_screen_questions(page):
            final_status = LAST_STATUS or "FAILED:unanswered-question"
            break

        # Review screen?
        submit_btn = page.get_by_role("button", name="Submit application").first
        try:
            if submit_btn.is_visible(timeout=1000):
                if do_submit:
                    submit_btn.click()
                    log("clicked Submit application")
                    time.sleep(3)
                    snap(page, "20-submitted")
                    final_status = "DONE:submitted"
                    status(final_status)
                else:
                    snap(page, "20-review")
                    final_status = "REVIEW_READY:not-submitted"
                    status(final_status)
                break
        except Exception:
            pass

        # Advance.
        clicked = False
        for name in ["Next", "Continue", "Review"]:
            try:
                btn = page.get_by_role("button", name=name).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    log(f"clicked '{name}'")
                    clicked = True
                    break
            except Exception:
                continue

        time.sleep(1.5)

        if not clicked:
            errors = read_validation_errors(page)
            if AUTONOMOUS:
                snap(page, "25-stuck")
                final_status = f"FAILED:stuck-no-next:{(errors or 'unknown')[:150]}"
                status(final_status)
                break
            status(f"NEED_INPUT:no-next-button:{errors or 'unknown'}")
            answer = wait_for_answer(timeout_seconds=300)
            if not answer:
                snap(page, "25-stuck")
                final_status = f"FAILED:stuck-no-next:{(errors or '')[:150]}"
                status(final_status)
                break
            try:
                ANSWER_FILE.unlink()
            except OSError:
                pass
            continue

        # Progress check via the page indicator.
        new_text = dialog_text(page, limit=2000)
        new_indicator = page_indicator(new_text)
        if new_indicator and new_indicator == indicator:
            same_screen_count += 1
            log(f"still on {indicator} (attempt {same_screen_count})")
            if same_screen_count >= 2:
                errors = read_validation_errors(page)
                if AUTONOMOUS:
                    snap(page, "25-stuck")
                    final_status = f"FAILED:stuck-on-{indicator}:{(errors or '')[:120]}"
                    status(final_status)
                    break
                status(f"NEED_INPUT:validation:{errors or new_text[:150]}")
                answer = wait_for_answer(timeout_seconds=300)
                if not answer:
                    snap(page, "25-stuck")
                    final_status = f"FAILED:stuck-on-{indicator}:{(errors or '')[:120]}"
                    status(final_status)
                    break
                try:
                    ANSWER_FILE.unlink()
                except OSError:
                    pass
                same_screen_count = 0
        else:
            same_screen_count = 0
            log(f"advanced: {indicator} -> {new_indicator}")

    if not final_status.startswith(("DONE", "REVIEW_READY")):
        snap(page, "30-final")
    cleanup_modal(page)
    return final_status


def main() -> int:
    global AUTONOMOUS
    AUTONOMOUS = "--autonomous" in sys.argv
    headless = "--headed" not in sys.argv
    do_submit = "--submit" in sys.argv

    # ---- Batch mode: one browser session applies to many jobs. ----
    # usage: python tools/linkedin_apply.py --batch <urls-file> <resume.pdf> [--submit] [--autonomous] [--headed]
    if "--batch" in sys.argv:
        idx = sys.argv.index("--batch")
        if idx + 2 >= len(sys.argv):
            print("usage: python tools/linkedin_apply.py --batch <urls-file> <resume.pdf> [--submit] [--autonomous]", flush=True)
            return 2
        urls_file = Path(sys.argv[idx + 1]).resolve()
        resume_path = Path(sys.argv[idx + 2]).resolve()
        if not resume_path.exists():
            print(f"resume not found: {resume_path}", flush=True)
            return 2
        urls = [u.strip() for u in urls_file.read_text(encoding="utf-8").splitlines() if u.strip()]
        try:
            if LOG_FILE.exists():
                LOG_FILE.unlink()
            log_lines.clear()
        except OSError:
            pass

        results: list[str] = []
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=headless,
                no_viewport=True,
                args=BROWSER_ARGS,
            )
            _inject_session(context)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                consecutive_failures = 0
                for i, url in enumerate(urls):
                    log(f"=== job {i + 1}/{len(urls)}: {url}")
                    st = apply_to_job(page, url, resume_path, do_submit)
                    results.append(f"{url} | {st}")
                    print(f"[batch] {url} -> {st}", flush=True)
                    # Session expired (authwall): stop the batch immediately.
                    # Re-applying with a dead session only triggers more
                    # rate-limiting; the marathon will alert + wait for a
                    # fresh session from R2.
                    if st == "FAILED:session-expired":
                        log("session expired mid-batch; stopping batch")
                        break
                    # Pace applications to stay under LinkedIn's rate limiter.
                    # Rapid back-to-back applications degrade the session
                    # (Easy Apply modal stops rendering, then page loads are
                    # blocked). A 15-35s pause between jobs keeps us under the
                    # threshold; consecutive failures trigger a longer backoff.
                    if st.startswith("DONE"):
                        consecutive_failures = 0
                        time.sleep(random.uniform(15, 35))
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= 2:
                            backoff = min(90, 45 + consecutive_failures * 15)
                            log(f"backing off {backoff:.0f}s after "
                                f"{consecutive_failures} consecutive failures")
                            time.sleep(backoff)
                        else:
                            time.sleep(random.uniform(20, 40))
            finally:
                # Export the (possibly refreshed) LinkedIn session so the
                # marathon can push it to R2 for the next Render boot.
                try:
                    import r2_sync
                    n = r2_sync.export_cookies_from_context(context)
                    if n:
                        print(f"[batch] exported {n} session cookies", flush=True)
                except Exception:
                    pass
                context.close()
        BATCH_RESULTS_FILE.write_text("\n".join(results), encoding="utf-8")
        done = sum(1 for r in results if "| DONE" in r)
        print(f"[batch] finished: {done}/{len(results)} submitted", flush=True)
        return 0

    # ---- Single-job mode. ----
    if len(sys.argv) < 3:
        print("usage: python tools/linkedin_apply.py <job-url> <resume.pdf> [--submit] [--headed] [--autonomous]", flush=True)
        return 2
    job_url = sys.argv[1]
    resume_path = Path(sys.argv[2]).resolve()
    if not resume_path.exists():
        status(f"FAILED:resume-not-found:{resume_path}")
        return 2
    for f in (ANSWER_FILE, LOG_FILE):
        try:
            if f.exists():
                f.unlink()
        except OSError:
            pass

    status("STARTING")
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            no_viewport=True,
            args=BROWSER_ARGS,
        )
        _inject_session(context)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            final = apply_to_job(page, job_url, resume_path, do_submit)
            return 0 if final.startswith(("DONE", "REVIEW_READY")) else 1
        finally:
            context.close()


if __name__ == "__main__":
    sys.exit(main())
