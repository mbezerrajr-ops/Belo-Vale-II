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

        await page.goto('file:///tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa/platform_full.html')
        await page.wait_for_timeout(300)
        await page.fill('#loginEmail', 'mbezerrajr@gmail.com')
        await page.fill('#loginPass', LEGACY_PASSWORD)
        await page.click('.login-btn')
        await page.wait_for_timeout(400)

        # --- add new user, then logout, login with new user ---
        await page.click('button[data-tab="usuarios"]')
        await page.wait_for_timeout(200)
        await page.click('#addUserBtn')
        await page.wait_for_timeout(200)
        rows = page.locator('#usersBody tr')
        last = rows.nth(await rows.count() - 1)
        eds = last.locator('.ed')
        await eds.nth(0).fill('') 
        await eds.nth(0).click()
        await page.keyboard.type('Teste Usuario')
        await eds.nth(1).click()
        await page.keyboard.type('teste@fazenda.com')
        await eds.nth(2).click()
        await page.keyboard.type('senha123')
        await page.wait_for_timeout(200)

        await page.click('#logoutBtn')
        await page.wait_for_timeout(200)
        await page.fill('#loginEmail', 'teste@fazenda.com')
        await page.fill('#loginPass', 'senha123')
        await page.click('.login-btn')
        await page.wait_for_timeout(400)
        who = await page.text_content('#whoLabel')
        print("Logged in as (new user test):", who)
        err_visible = await page.is_visible('#loginScreen')
        print("login screen still visible (should be False):", err_visible)

        # --- edit an insumo price and check dashboard recompute ---
        await page.click('button[data-tab="insumos"]')
        await page.wait_for_timeout(200)
        preco_input = page.locator('#insumosBody tr[data-id="concentrado"] .preco-atual')
        await preco_input.fill('5.00')
        await page.wait_for_timeout(200)

        await page.click('button[data-tab="dashboard"]')
        await page.wait_for_timeout(300)
        custo_kpi = await page.locator('.kpi').nth(3).locator('.value').text_content()
        print("Custo/dia (lote) apos mudar preco concentrado p/ 5.00:", custo_kpi)

        await page.screenshot(path='p_after_edit.png', full_page=True)

        # --- remove a vaca row and check count updates ---
        await page.click('button[data-tab="vacas"]')
        await page.wait_for_timeout(200)
        before_count = await page.locator('#vacasBody tr').count()
        await page.locator('#vacasBody tr').first.locator('.row-del').click()
        await page.wait_for_timeout(200)
        after_count = await page.locator('#vacasBody tr').count()
        print("vacas before/after delete:", before_count, after_count)

        print("Errors total:", errors)
        await browser.close()

asyncio.run(main())
