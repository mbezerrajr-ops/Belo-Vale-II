import asyncio
from playwright.async_api import async_playwright

import os

# Credencial legada rotacionada: o valor real nunca é versionado. Defina
# BV_LEGACY_PASSWORD no ambiente para rodar contra um artefato real.
LEGACY_PASSWORD = os.environ.get("BV_LEGACY_PASSWORD", "LEGADO-SEM-SEGURANCA")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        page = await browser.new_page(viewport={"width":1320,"height":1000})
        errors = []
        page.on("console", lambda msg: errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        with open('platform.html', encoding='utf-8') as f:
            frag = f.read()
        full = f"<!doctype html><html><head><meta charset='utf-8'></head><body>{frag}</body></html>"
        with open('platform_full.html', 'w', encoding='utf-8') as f:
            f.write(full)

        await page.goto('file:///tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa/platform_full.html')
        await page.wait_for_timeout(400)
        await page.screenshot(path='p_login.png')
        print("Errors after load:", errors)

        # wrong login
        await page.fill('#loginEmail', 'errado@x.com')
        await page.fill('#loginPass', 'errado')
        await page.click('.login-btn')
        await page.wait_for_timeout(200)
        err_text = await page.text_content('#loginError')
        print("wrong login error text:", err_text)

        # correct login
        await page.fill('#loginEmail', 'mbezerrajr@gmail.com')
        await page.fill('#loginPass', LEGACY_PASSWORD)
        await page.click('.login-btn')
        await page.wait_for_timeout(500)
        print("Errors after login:", errors)
        await page.screenshot(path='p_dashboard.png', full_page=True)

        # go to Vacas tab
        await page.click('button[data-tab="vacas"]')
        await page.wait_for_timeout(300)
        await page.screenshot(path='p_vacas.png')

        # go to Insumos tab
        await page.click('button[data-tab="insumos"]')
        await page.wait_for_timeout(300)
        await page.screenshot(path='p_insumos.png')

        # go to Usuarios tab
        await page.click('button[data-tab="usuarios"]')
        await page.wait_for_timeout(300)
        await page.screenshot(path='p_usuarios.png')

        print("Errors total:", errors)
        await browser.close()

asyncio.run(main())
