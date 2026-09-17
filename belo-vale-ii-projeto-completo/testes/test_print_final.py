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
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        popups = []
        page.on("popup", lambda p2: popups.append(p2))
        # Neutralize window.print so this test doesn't hang on a native dialog,
        # while still letting us verify the toast fires regardless.
        await page.add_init_script("window.print = () => { window.__printCalled = (window.__printCalled||0)+1; };")
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", LEGACY_PASSWORD)
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(200)

        await page.click("#btnImprimirLista")
        await page.wait_for_timeout(150)
        await page.click("#mGo")
        await page.wait_for_timeout(300)

        toast_class = await page.get_attribute("#bv2Toast", "class")
        toast_text = await page.inner_text("#bv2Toast")
        rows = await page.locator("#printArea table tbody tr").count()
        area_display = await page.eval_on_selector("#printArea", "el => getComputedStyle(el).display")
        print_called = await page.evaluate("window.__printCalled || 0")
        print("toast class:", toast_class)
        print("toast text:", toast_text)
        print("printArea rows:", rows)
        print("printArea display on screen (should be none):", area_display)
        print("window.print() calls:", print_called)
        print("popups (should be 0):", len(popups))
        print("no window.claude at all - confirm no crash. errors:", errors)

        # media print rendering check
        await page.emulate_media(media="print")
        await page.wait_for_timeout(150)
        await page.screenshot(path=f"{BASE}/shots/10_print_media_final.png", full_page=False)

        await browser.close()

asyncio.run(main())
