from patchright.sync_api import sync_playwright
import json

with open("tools/.apply_debug/radio-dump.txt", encoding="utf-8") as f:
    dump = f.read()

html = dump.split("=== RAW HTML of form area (first 6000 chars) ===\n")[1]

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content("<div>" + html + "</div>")
    
    # Method 1: Playwright locator click on label
    print("Method 1: Playwright click on label for input")
    # In the HTML:
    # <div role="radio" aria-label="Yes">
    #   ... <input id="«rr»" type="radio" ...>
    #   <label for="«rr»"></label>
    #   <p>Yes</p>
    
    # Try clicking the label
    try:
        page.locator("label[for='«rr»']").click(force=True)
    except Exception as e:
        print("label click error:", e)
        
    check_js = """() => {
        const radios = document.querySelectorAll('input[type="radio"], [role="radio"]');
        return Array.from(radios).map(r => ({
            tag: r.tagName,
            id: r.id,
            role: r.getAttribute('role'),
            checked: r.checked,
            aria_checked: r.getAttribute('aria-checked')
        }));
    }"""
    print("After label click:")
    print(json.dumps(page.evaluate(check_js), indent=2))
    
    # Method 2: Click the <p> containing 'Yes'
    print("\nMethod 2: Playwright click on p containing 'Yes'")
    page.locator("div[role='radio'][aria-label='Yes'] p").click(force=True)
    print("After p click:")
    print(json.dumps(page.evaluate(check_js), indent=2))
    
    # Method 3: Click input directly with Playwright check()
    print("\nMethod 3: Playwright input check()")
    page.locator("input[id='«rr»']").check(force=True)
    print("After input check():")
    print(json.dumps(page.evaluate(check_js), indent=2))
    
    # Method 4: JS click on input
    print("\nMethod 4: JS click on input")
    page.evaluate("document.getElementById('«rs»').click()")
    print("After JS click on «rs»:")
    print(json.dumps(page.evaluate(check_js), indent=2))
    
    browser.close()
