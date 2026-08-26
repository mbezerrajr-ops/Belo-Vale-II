import asyncio
from playwright.async_api import async_playwright

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
        await page.fill('#loginPass', 'belovale2026')
        await page.click('.login-btn')
        await page.wait_for_timeout(400)

        await page.click('button[data-tab="dashboard"]')
        await page.wait_for_timeout(300)
        custo_before = await page.locator('.kpi').nth(3).locator('.value').text_content()
        print("Custo/dia (lote) ANTES:", custo_before)

        await page.click('button[data-tab="insumos"]')
        await page.wait_for_timeout(200)
        preco_input = page.locator('#insumosBody tr[data-id="concentrado"] .preco-atual')
        await preco_input.fill('5.00')
        await preco_input.dispatch_event('input')
        await page.wait_for_timeout(200)

        await page.click('button[data-tab="dashboard"]')
        await page.wait_for_timeout(300)
        custo_after = await page.locator('.kpi').nth(3).locator('.value').text_content()
        print("Custo/dia (lote) DEPOIS de mudar concentrado p/ R$5,00:", custo_after)

        # vaca custo cell should also change
        await page.click('button[data-tab="vacas"]')
        await page.wait_for_timeout(200)
        custo_cell = await page.locator('#vacasBody tr[data-lote="LOTE 1"]').first.locator('.custo-cell').text_content()
        print("Custo/dia de uma vaca do Lote 1 apos mudanca:", custo_cell)

        before_count = await page.locator('#vacasBody tr').count()
        await page.locator('#vacasBody tr').first.locator('.row-del').click()
        await page.wait_for_timeout(150)
        after_count = await page.locator('#vacasBody tr').count()
        print("vacas antes/depois de remover 1 linha:", before_count, after_count)

        # test lote pill cycling
        pill = page.locator('#vacasBody tr').first.locator('[data-cycle="lote"]')
        before_label = await pill.text_content()
        await pill.click()
        after_label = await pill.text_content()
        print("lote pill antes/depois do clique:", before_label, "->", after_label)

        print("Errors total:", errors)
        await browser.close()

asyncio.run(main())
