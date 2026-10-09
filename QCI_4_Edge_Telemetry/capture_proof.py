"""Fresh-browser screenshot of actual measured review DOM, without user credentials."""
from pathlib import Path
import hashlib
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1];REPORTS=ROOT/'reports/qci4'

def main():
    blocked=[]
    with sync_playwright() as runtime:
        browser=runtime.chromium.launch(channel='msedge',headless=True,args=['--disable-background-networking','--disable-component-update'])
        try:
            context=browser.new_context(viewport={'width':1280,'height':1000},device_scale_factor=1)
            def route(value):
                if value.request.url.startswith(('file:','data:','blob:')):value.continue_()
                else:blocked.append(value.request.url);value.abort()
            context.route('**/*',route);page=context.new_page();page.goto((REPORTS/'review.html').as_uri(),wait_until='load')
            assert page.title()=='QCI-4 measured local review' and 'OFFLINE' in page.inner_text('body') and 'RECOVERING' in page.inner_text('body')
            image=REPORTS/'proof_of_work.png';page.screenshot(path=str(image),full_page=True)
            proof={'browser':'fresh headless Microsoft Edge','surface':'actual generated review DOM with saved measured status/terminal evidence; not claimed live Streamlit or OS terminal',
                'html_sha256':hashlib.sha256((REPORTS/'review.html').read_bytes()).hexdigest(),'screenshot_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                'external_page_requests_blocked':blocked,'user_profile_or_credentials_accessed':False,
                'in_app_browser_bootstrap':'failed before setup: kernel assets path not found (os error 3)'}
            (REPORTS/'screenshot_proof.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
        finally:browser.close()
    print('Actual local review DOM captured and browser disposed.')
if __name__=='__main__':main()
