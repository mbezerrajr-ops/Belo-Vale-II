import asyncio
from playwright.async_api import async_playwright

import os

# Credencial legada rotacionada: o valor real nunca é versionado. Defina
# BV_LEGACY_PASSWORD no ambiente para rodar contra um artefato real.
LEGACY_PASSWORD = os.environ.get("BV_LEGACY_PASSWORD", "LEGADO-SEM-SEGURANCA")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        page = await browser.new_page(viewport={"width":1320,"height":1000}, color_scheme="dark")
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        await page.goto('file:///tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa/platform_full.html')
        await page.wait_for_timeout(300)
        await page.screenshot(path='p_dark_login.png')
        await page.fill('#loginEmail', 'mbezerrajr@gmail.com')
        await page.fill('#loginPass', LEGACY_PASSWORD)
        await page.click('.login-btn')
        await page.wait_for_timeout(400)
        await page.screenshot(path='p_dark_dashboard.png')
        await page.click('button[data-tab="vacas"]')
        await page.wait_for_timeout(200)
        await page.screenshot(path='p_dark_vacas.png')
        print("errors", errors)
        await browser.close()

asyncio.run(main())
