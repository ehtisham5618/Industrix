"""Screenshot real generated review DOM with actual metrics in a fresh browser."""
from pathlib import Path
import hashlib
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci3'

def main():
    blocked=[]
    with sync_playwright() as runtime:
        browser=runtime.chromium.launch(channel='msedge',headless=True,args=['--disable-background-networking','--disable-component-update'])
        try:
            context=browser.new_context(viewport={'width':1280,'height':1000},device_scale_factor=1)
            def route(request):
                if request.request.url.startswith(('file:','data:','blob:')):request.continue_()
                else:blocked.append(request.request.url);request.abort()
            context.route('**/*',route)
            page=context.new_page();page.goto((REPORTS/'review.html').as_uri(),wait_until='load')
            assert page.title()=='QCI-3 measured local review'
            assert 'INFO' in page.inner_text('body') and 'CRITICAL' in page.inner_text('body')
            assert 'Actual test terminal output' in page.inner_text('body')
            image=REPORTS/'proof_of_work.png';page.screenshot(path=str(image),full_page=True)
            (REPORTS/'screenshot_proof.json').write_text(json.dumps({'browser':'fresh headless Microsoft Edge',
                'surface':'actual generated local review HTML; not a claimed live Streamlit or operating-system terminal screenshot',
                'html_sha256':hashlib.sha256((REPORTS/'review.html').read_bytes()).hexdigest(),
                'screenshot_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'external_page_requests_blocked':blocked,
                'in_app_browser_bootstrap':'failed before setup: system cannot find kernel assets (os error 3)',
                'user_profile_or_credentials_accessed':False},indent=2)+'\n',encoding='utf-8')
        finally:browser.close()
    print('Actual measured review page captured with a fresh browser.')

if __name__=='__main__':main()
