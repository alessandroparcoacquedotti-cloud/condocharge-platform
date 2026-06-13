from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _login(page: Page, *, username: str, password: str) -> None:
    page.goto("/login", wait_until="domcontentloaded")
    page.get_by_label("Nome utente").fill(username)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Accedi").click()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture portfolio screenshots from a running CondoCharge dev server.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5173", help="Frontend base URL (Vite dev server).")
    parser.add_argument("--out-dir", default=str(Path("docs") / "images"), help="Output directory for PNGs.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    _ensure_dir(out_dir)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            base_url=args.base_url,
            viewport={"width": 1440, "height": 900},
            locale="it-IT",
        )
        page = context.new_page()

        page.goto("/login", wait_until="domcontentloaded")
        page.wait_for_selector(".auth-card")
        page.screenshot(path=str(out_dir / "01-login.png"))

        _login(page, username="demo_admin", password="demo_admin")
        page.wait_for_url("**/admin/panoramica", timeout=20_000)
        page.get_by_role("heading", name="Panoramica").wait_for(timeout=20_000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / "02-admin-dashboard.png"))

        page.goto("/admin/addebiti", wait_until="domcontentloaded")
        page.get_by_role("heading", name="Addebiti").wait_for(timeout=20_000)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(out_dir / "04-billing-reconciliation.png"))

        page.get_by_role("button", name="Esci").click()
        page.wait_for_url("**/login**", timeout=20_000)

        _login(page, username="demo_resident_1", password="resident1")
        page.wait_for_url("**/resident/**", timeout=20_000)
        page.goto("/resident/consumi", wait_until="domcontentloaded")
        page.get_by_role("heading", name="I miei consumi").wait_for(timeout=20_000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_dir / "03-resident-dashboard.png"))

        context.close()
        browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

