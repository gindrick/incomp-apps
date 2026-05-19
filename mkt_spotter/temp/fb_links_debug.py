import os, re, json
from dotenv import load_dotenv; load_dotenv()
from playwright.sync_api import sync_playwright

graphql_responses = []

def handle_response(response):
    try:
        if '/api/graphql/' not in response.url:
            return
        body = response.body()
        text = body.decode('utf-8', errors='replace')
        if len(text) > 100:
            graphql_responses.append(text)
    except Exception:
        pass

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 900}
    )
    page = ctx.new_page()
    page.on('response', handle_response)

    page.goto('https://www.facebook.com/login', wait_until='networkidle', timeout=30000)
    for btn in page.locator('button, [role=button]').all():
        try:
            if any(kw in btn.inner_text().lower() for kw in ('allow', 'accept', 'povolit', 'erlauben')):
                btn.click(); page.wait_for_timeout(2000); break
        except: pass
    page.wait_for_selector('[name=email]', timeout=5000)
    page.fill('[name=email]', os.environ['FB_USERNAME'])
    page.fill('[name=pass]', os.environ['FB_PASSWORD'])
    page.press('[name=pass]', 'Enter')
    page.wait_for_url(re.compile(r'facebook\.com/(home|feed|\?|\Z)'), timeout=15000)

    graphql_responses.clear()
    page.goto('https://www.facebook.com/HettichCR', wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(2000)
    for _ in range(6):
        page.evaluate('window.scrollBy(0, window.innerHeight*2)')
        page.wait_for_timeout(2000)

    print(f'GraphQL responses > 100 chars: {len(graphql_responses)}')
    for i, r in enumerate(graphql_responses):
        print(f'\n--- Response {i} (len={len(r)}) ---')
        # Show first 400 chars
        print(repr(r[:400]))

    # Save largest for analysis
    if graphql_responses:
        largest = max(graphql_responses, key=len)
        with open('temp/graphql_largest.json', 'w', encoding='utf-8') as f:
            f.write(largest)
        print(f'\nSaved largest ({len(largest)} chars) to temp/graphql_largest.json')

    browser.close()
