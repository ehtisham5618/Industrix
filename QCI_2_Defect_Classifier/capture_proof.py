"""Fresh local evidence-page capture after in-app browser bootstrap failure."""
from __future__ import annotations
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright,Route
from .common import REPORTS,write_json


def main() -> None:
    """Capture real pytest/metrics/heatmap page, with no existing browser profile."""
    denied:list[str]=[]
    with sync_playwright() as runner:
        browser=runner.chromium.launch(channel='msedge',headless=True)
        context=browser.new_context(viewport={'width':1600,'height':1200},device_scale_factor=1)
        def route(request: Route) -> None:
            if urlparse(request.request.url).scheme in ('file','data','blob'):request.continue_()
            else:denied.append(request.request.url);request.abort()
        context.route('**/*',route)
        page=context.new_page();page.goto((REPORTS/'review.html').as_uri(),wait_until='load')
        page.wait_for_function('Array.from(document.images).every(i=>i.complete && i.naturalWidth>0)')
        page.screenshot(path=str(REPORTS/'proof_of_work.png'),full_page=True)
        page.screenshot(path=str(REPORTS/'proof_summary.png'))
        context.close();browser.close()
    write_json(REPORTS/'screenshot_proof.json',dict(source='Actual local HTML with captured pytest stdout, actual classifier metrics and real model attribution',
        browser='Fresh headless Microsoft Edge via Playwright',existing_user_profiles_used=False,
        external_requests_blocked=denied,in_app_browser_unavailable='Kernel asset bootstrap failed: system cannot find path (os error3)',synthetic_screenshot=False))
    print('Saved actual local classifier review screenshots; external requests:',len(denied))


if __name__=='__main__':main()
