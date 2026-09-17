import asyncio, sys
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
        page = await browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"PAGEERROR: {exc}"))
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.wait_for_timeout(300)

        # login
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", LEGACY_PASSWORD)
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(500)
        visible = await page.is_visible("#app")
        print("app visible after login:", visible)
        await page.screenshot(path=f"{BASE}/shots/1_dashboard.png", full_page=True)

        # check kpi row populated
        kpi_text = await page.inner_text("#kpiRow")
        print("KPI row snippet:", kpi_text[:200].replace("\n"," | "))

        # go to Vacas tab
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(300)
        rows = await page.locator("#vacasBody tr").count()
        print("vacas rows rendered:", rows)
        await page.screenshot(path=f"{BASE}/shots/2_vacas.png", full_page=False)

        # double-click edit a name
        first_span = page.locator(".ed-text[data-field=nome]").first
        await first_span.dblclick()
        await page.wait_for_timeout(150)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("TESTE EDITADO")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)
        name_after = await page.locator("#vacasBody tr").first.locator("td").nth(2).inner_text()
        print("name after edit:", name_after)

        # cycle lote pill
        pill = page.locator("button[data-cycle=lote]").first
        before = await pill.inner_text()
        await pill.click()
        await page.wait_for_timeout(200)
        after = await pill.inner_text()
        print("lote pill cycle:", before, "->", after)

        # checkbox select + print modal
        await page.locator(".vSelRow").first.check()
        await page.wait_for_timeout(150)
        await page.click("#btnImprimirLista")
        await page.wait_for_timeout(200)
        modal_visible = await page.is_visible(".modal")
        print("print modal visible:", modal_visible)
        await page.screenshot(path=f"{BASE}/shots/3_print_modal.png", full_page=False)
        await page.click("#mCancel")
        await page.wait_for_timeout(150)

        # go to Insumos tab
        await page.click("button[data-tab=insumos]")
        await page.wait_for_timeout(300)
        await page.screenshot(path=f"{BASE}/shots/4_insumos.png", full_page=True)
        card_count = await page.locator(".ins-card").count()
        print("insumo cards:", card_count)

        # register new price
        await page.fill("#np-i1", "2.50")
        await page.click("button[data-action='reg-preco'][data-id=i1]")
        await page.wait_for_timeout(300)
        price_now = await page.locator("[data-ins=i1] .price-now").inner_text()
        print("price after update:", price_now)

        # go to Usuarios tab
        await page.click("button[data-tab=usuarios]")
        await page.wait_for_timeout(300)
        await page.screenshot(path=f"{BASE}/shots/5_usuarios.png", full_page=True)
        user_rows = await page.locator("table.cadtable tbody tr").count()
        print("user rows:", user_rows)

        # go back to dashboard and test filters
        await page.click("button[data-tab=dashboard]")
        await page.wait_for_timeout(300)
        await page.click("#segLote button[data-value='LOTE 1']")
        await page.wait_for_timeout(300)
        summary = await page.inner_text("#dashSummary")
        print("dash summary after lote filter:", summary)
        await page.screenshot(path=f"{BASE}/shots/6_dashboard_filtered.png", full_page=True)

        print("CONSOLE ERRORS:", errors[:20])
        await browser.close()

asyncio.run(main())
