from patchright.sync_api import sync_playwright
import json

with open("tools/.apply_debug/radio-dump.txt", encoding="utf-8") as f:
    dump = f.read()

html = dump.split("=== RAW HTML of form area (first 6000 chars) ===\n")[1]

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    page.set_content("<div>" + html + "</div>")
    
    group = {
      "fi": 0,
      "question": "Have you completed the following level of education: Bachelor's Degree?*",
      "options": [
        {
          "ri": 0,
          "label": "Yes",
          "checked": False
        },
        {
          "ri": 1,
          "label": "No",
          "checked": False
        }
      ]
    }
    
    auto = "Yes"
    target = group["options"][0]
    
    print("Testing old Python locator code:")
    try:
        fs_loc = page.locator("fieldset[role='radiogroup'], fieldset").nth(group["fi"])
        print("fs_loc count:", fs_loc.count())
        radio_loc = fs_loc.locator("[role='radio'], input[type='radio'], label").nth(target["ri"])
        print("radio_loc count:", radio_loc.count())
        print("radio_loc html:", radio_loc.evaluate("el => el.outerHTML"))
        radio_loc.click(force=True)
        print("Click succeeded!")
    except Exception as exc:
        print("Click threw exception:", exc)
        
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
    print("State after click:")
    print(json.dumps(page.evaluate(check_js), indent=2))
    browser.close()
