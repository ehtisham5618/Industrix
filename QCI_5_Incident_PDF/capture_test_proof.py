"""Show actual saved pytest output in a local review page, not a fabricated OS terminal."""
import hashlib
import html
import json
from playwright.sync_api import sync_playwright
from .verify import REPORTS,write

def main():
    summary=json.loads((REPORTS/'qci5_summary.json').read_text())
    page=REPORTS/'validation_proof.html'
    markup='''<!doctype html><html><head><meta charset="utf-8"><title>QCI-5 saved validation evidence</title>
<style>body{font:16px system-ui;margin:40px;color:#17344d;background:#f7f9fb}main{max-width:1100px;margin:auto;background:white;padding:32px;border:1px solid #dbe3eb}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px monospace;padding:20px;background:#eef3f7}p{line-height:1.6}</style></head><body><main>
<h1>QCI-5 local reporting validation</h1><p>Actual saved pytest output rendered for review. This image is not an OS-terminal capture.</p>
'''
    markup+='<p>QCI-5: '+str(summary['tests']['passed'])+' passed / '+str(summary['tests']['collected'])+' collected. '
    markup+='500 real incident exports; matched-window memory drift '+format(summary['memory']['matched_window_drift_percent'],'.6f')+'%.</p>'
    markup+='<h2>QCI-5 pytest output</h2><pre>'+html.escape((REPORTS/'pytest_output.txt').read_text())+'</pre>'
    markup+='<h2>Repository result</h2><p>'+str(summary['repository_tests']['passed'])+' passed; two inherited CPU1 size/mAP failures. Full release gates remain unmet.</p>'
    markup+='<p>Offline CLI/API export and live local Streamlit download verified. No GPU or runtime asset download.</p></main></body></html>'
    page.write_text(markup,encoding='utf-8');blocked=[]
    with sync_playwright() as runtime:
        browser=runtime.chromium.launch(channel='msedge',headless=True,args=['--disable-background-networking','--disable-component-update'])
        try:
            context=browser.new_context(viewport={'width':1280,'height':1000})
            def route(value):
                if value.request.url.startswith(('file:','data:','blob:')):value.continue_()
                else:blocked.append(value.request.url);value.abort()
            context.route('**/*',route);view=context.new_page();view.goto(page.as_uri(),wait_until='load')
            assert '42 passed' in view.inner_text('body')
            target=REPORTS/'test_validation_proof.png';view.screenshot(path=str(target),full_page=True)
            write(REPORTS/'test_screenshot_proof.json',dict(surface='Actual saved test output rendered in local HTML, not an OS terminal',
                screenshot=target.name,html_sha256=hashlib.sha256(page.read_bytes()).hexdigest(),
                screenshot_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),external_page_requests_blocked=blocked))
        finally:browser.close()
    print('Actual saved validation output captured for local review.')
if __name__=='__main__':main()
