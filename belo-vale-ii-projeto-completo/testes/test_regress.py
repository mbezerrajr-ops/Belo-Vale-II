import asyncio
from playwright.async_api import async_playwright

import os

# Credencial legada rotacionada: o valor real nunca é versionado. Defina
# BV_LEGACY_PASSWORD no ambiente para rodar contra um artefato real.
LEGACY_PASSWORD = os.environ.get("BV_LEGACY_PASSWORD", "LEGADO-SEM-SEGURANCA")

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

MOCK = """
window.claude = {
  __saveCalls: [],
  use: async function(name) {
    if (name === "artifact") return { publish: async () => {} };
    if (name === "downloads") {
      return { save: async (req) => { window.claude.__saveCalls.push(req.filename); return { status: "saved" }; } };
    }
    return null;
  }
};
"""

async def main():
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        await page.add_init_script(MOCK)
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", LEGACY_PASSWORD)
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)

        # dashboard sanity
        kpi = await page.inner_text("#kpiRow")
        print("dashboard KPI ok:", "VACAS NA SELEÇÃO" in kpi)

        # vacas tab: formulario em branco
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(200)
        await page.click("#btnFormBranco")
        await page.wait_for_timeout(150)
        await page.click("#mGo")
        await page.wait_for_timeout(300)
        calls = await page.evaluate("window.claude.__saveCalls")
        print("formulario branco save calls:", calls)
        toast = await page.inner_text("#bv2Toast")
        print("toast:", toast)

        # edit still works
        span = page.locator(".ed-text[data-field=nome]").first
        await span.dblclick()
        await page.wait_for_timeout(100)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("REGRESSAO OK")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(200)
        await page.fill("#vBusca", "REGRESSAO OK")
        await page.wait_for_timeout(150)
        found = await page.locator("#vacasBody").inner_text()
        print("edit persisted:", "REGRESSAO OK" in found)

        # usuarios tab edit still works
        await page.click("button[data-tab=usuarios]")
        await page.wait_for_timeout(200)
        nome_span = page.locator(".ed-text[data-field=nome]").first
        exists = await nome_span.count()
        print("usuarios nome editable field present:", exists > 0)

        print("errors:", errors)
        await browser.close()

asyncio.run(main())
