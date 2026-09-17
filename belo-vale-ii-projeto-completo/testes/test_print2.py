import asyncio
from playwright.async_api import async_playwright

import os

# Credencial legada rotacionada: o valor real nunca é versionado. Defina
# BV_LEGACY_PASSWORD no ambiente para rodar contra um artefato real.
LEGACY_PASSWORD = os.environ.get("BV_LEGACY_PASSWORD", "LEGADO-SEM-SEGURANCA")

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

async def main():
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("pageerror", lambda exc: errors.append(f"PAGEERROR: {exc}"))
        popups = []
        page.on("popup", lambda p2: popups.append(p2))
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", LEGACY_PASSWORD)
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(300)

        # capture print() calls instead of letting real dialog show
        await page.evaluate("window.__printCalls = 0; window.print = () => { window.__printCalls++; };")

        await page.click("#btnImprimirLista")
        await page.wait_for_timeout(200)
        await page.click("#mGo")
        await page.wait_for_timeout(300)

        print_calls = await page.evaluate("window.__printCalls")
        area_html = await page.eval_on_selector("#printArea", "el => el.innerHTML")
        area_display_screen = await page.eval_on_selector("#printArea", "el => getComputedStyle(el).display")
        rows_in_area = await page.locator("#printArea table tbody tr").count()
        print("print() called:", print_calls)
        print("printArea visible on screen (should be 'none'):", area_display_screen)
        print("rows rendered in printArea:", rows_in_area)
        print("printArea has content:", len(area_html) > 100)
        print("popups opened (should be 0):", len(popups))
        print("errors:", errors)

        # sanity: form-branco flow too
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(200)
        await page.click("#btnFormBranco")
        await page.wait_for_timeout(200)
        await page.click("#mGo")
        await page.wait_for_timeout(300)
        title_area = await page.eval_on_selector("#printArea h1", "el => el.textContent")
        print("form branco title:", title_area)

        await browser.close()

asyncio.run(main())
