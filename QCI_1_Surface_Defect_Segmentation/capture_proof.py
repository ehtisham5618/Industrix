"""Capture the actual local evidence page in a fresh headless Edge context.

Used after the in-app browser failed to bootstrap (kernel assets/path error).
No existing user profiles, cookies, authentication or remote pages are accessed.
"""
from __future__ import annotations
import json
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, Route
from .config import ROOT


def main() -> None:
    """Screenshot real captured terminal output and actual dataset overlays."""
    output=ROOT/'reports/qci1'; denied: list[str]=[]
    with sync_playwright() as runner:
        browser=runner.chromium.launch(channel='msedge',headless=True)
        context=browser.new_context(viewport={'width':1600,'height':1200},device_scale_factor=1)
        def route(request: Route) -> None:
            if urlparse(request.request.url).scheme in ('file','data','blob'): request.continue_()
            else:
                denied.append(request.request.url);request.abort()
        context.route('**/*',route)
        page=context.new_page();page.goto((output/'review.html').as_uri(),wait_until='load')
        page.wait_for_function('Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)')
        page.screenshot(path=str(output/'proof_of_work.png'),full_page=True)
        page.screenshot(path=str(output/'proof_summary.png'))
        title=page.title();context.close();browser.close()
    (output/'screenshot_proof.json').write_text(json.dumps(dict(browser='Fresh headless Microsoft Edge context via Playwright',
        source='Local HTML containing actual pytest stdout and real source/mask grids',title=title,
        in_app_browser_unavailable='Kernel asset bootstrap failed: system cannot find path (os error 3)',
        external_requests_blocked=denied, existing_user_profiles_used=False, synthetic_capture=False),indent=2)+'\n',encoding='utf-8')
    print('Saved actual local review-page screenshots; external requests:',len(denied))


if __name__=='__main__':main()
