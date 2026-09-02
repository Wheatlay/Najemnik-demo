"""Playwright acceptance flow for a running DEMO_MODE instance."""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright


def _open_notes(page):
    page.locator('[data-demo="listing-2"]').click()
    page.locator('#drawer-body [data-tour-group="Notatki"]').click()
    notes = page.locator('#drawer-body textarea[hx-vals*="notatki"]')
    notes.wait_for(state="visible")
    return notes


def verify(base_url: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context_a = browser.new_context()
        context_b = browser.new_context()
        page_a = context_a.new_page()
        page_b = context_b.new_page()

        page_a.goto(f"{base_url}/galeria")
        page_b.goto(f"{base_url}/galeria")
        assert page_a.locator("[data-demo]").count() == 3
        assert page_b.locator("[data-demo]").count() == 3
        assert context_a.cookies()[0]["value"] != context_b.cookies()[0]["value"]

        health = page_a.request.get(f"{base_url}/healthz").json()
        assert health["status"] == "ok" and health["demo"] is True and health["version"]

        page_a.goto(f"{base_url}/galeria?samouczek=1")
        page_a.locator(".tour-card").wait_for(state="visible")
        assert page_a.evaluate("window.tourStepInfo().active") is True
        page_a.get_by_role("button", name="Pełny samouczek").click()
        page_a.wait_for_function("window.tourStepInfo().index === 1")
        # Explanatory steps must advance to the chosen demo listing;
        # this catches stale data-demo selectors after fixture changes.
        page_a.locator('[data-tour-action="next"]').click()
        page_a.wait_for_function("window.tourStepInfo().index === 2")
        page_a.locator('[data-tour-action="next"]').click()
        page_a.wait_for_function("window.tourStepInfo().index === 3")
        page_a.locator('[data-demo="listing-2"]').click()
        page_a.locator("#drawer-body").wait_for(state="visible")
        page_a.wait_for_function("window.tourStepInfo().index === 4")
        page_a.locator('[data-tour-action="pause"]').click()
        page_a.locator("#tour-launcher.tour-resume-pulse").wait_for(state="visible")
        page_a.locator("#tour-launcher").click()
        page_a.locator(".tour-card").wait_for(state="visible")
        page_a.locator('[data-tour-action="end"]').click()

        page_a.goto(f"{base_url}/pomoc")
        page_a.locator(".help-page").wait_for(state="visible")
        assert page_a.locator(".help-card").count() == 4

        rooms = page_a.locator('#filter-form input[name="rooms_min"]')
        rooms.fill("3")
        rooms.press("Tab")
        page_a.wait_for_function("document.querySelectorAll('[data-demo]').length === 2")

        page_a.goto(f"{base_url}/galeria")
        page_a.locator('[data-tour="compare-toggle"]').click()
        page_a.locator('[data-demo="listing-2"]').click()
        page_a.locator('[data-demo="listing-3"]').click()
        page_a.locator('[data-tour="compare-go"]').click()
        page_a.wait_for_url("**/porownaj2?ids=**")
        page_a.locator("#compare-focus").wait_for(state="visible")

        page_a.goto(f"{base_url}/mapa")
        page_a.locator("#map").wait_for(state="visible")

        page_a.goto(f"{base_url}/galeria")
        notes_a = _open_notes(page_a)
        notes_a.fill("Browser A isolated edit")
        notes_a.blur()
        page_a.wait_for_timeout(600)

        page_b.goto(f"{base_url}/galeria")
        notes_b = _open_notes(page_b)
        assert notes_b.input_value() != "Browser A isolated edit"

        page_a.locator('#drawer-body button:has-text("+ Dodaj do rankingu")').click()
        page_a.locator("#drawer-body").get_by_text("#1", exact=True).wait_for()
        page_a.goto(f"{base_url}/panel")
        page_a.locator("span.rounded-full").filter(has_text="1").first.wait_for()

        page_a.goto(f"{base_url}/galeria")
        page_a.once("dialog", lambda dialog: dialog.accept())
        page_a.get_by_role("button", name="Resetuj demo").click()
        page_a.wait_for_timeout(1000)
        page_a.locator(".tour-card").wait_for(state="visible")
        assert page_a.evaluate("window.tourStepInfo().index") == 0
        page_a.locator('[data-tour-action="pause"]').click()
        notes_after_reset = _open_notes(page_a)
        assert notes_after_reset.input_value() != "Browser A isolated edit"

        disabled = page_a.request.post(f"{base_url}/ingest")
        assert disabled.status == 403
        assert disabled.json()["detail"] == "demo_mode_disabled"

        context_a.close()
        context_b.close()
        browser.close()


if __name__ == "__main__":
    verify(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
    print("Najemnik DEMO_MODE Playwright verification passed")
