import asyncio
from playwright.async_api import async_playwright

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await browser.new_page(viewport={"width": 1400, "height": 1000})
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", "belovale2026")
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(300)

        first_span = page.locator(".ed-text[data-field=nome]").first
        orig = await first_span.inner_text()
        await first_span.dblclick()
        await page.wait_for_timeout(150)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("TESTE EDITADO")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)

        await page.fill("#vBusca", "TESTE EDITADO")
        await page.wait_for_timeout(200)
        rows = await page.locator("#vacasBody tr").count()
        txt = await page.locator("#vacasBody").inner_text()
        print("orig name:", orig)
        print("rows after search:", rows)
        print("found TESTE EDITADO:", "TESTE EDITADO" in txt)

        # test select-all checkbox
        await page.fill("#vBusca", "")
        await page.wait_for_timeout(200)
        await page.check("#vSelAll")
        await page.wait_for_timeout(200)
        checked = await page.locator(".vSelRow:checked").count()
        print("checked after select-all:", checked)

        # test status/situacao pills cycling through all states
        sit_pill = page.locator("button[data-cycle=situacao]").first
        vals = []
        for i in range(5):
            vals.append(await sit_pill.inner_text())
            await sit_pill.click()
            await page.wait_for_timeout(100)
            sit_pill = page.locator("button[data-cycle=situacao]").first
        print("situacao cycle:", vals)

        status_pill = page.locator("button[data-cycle=status]").first
        vals2 = []
        for i in range(4):
            vals2.append(await status_pill.inner_text())
            await status_pill.click()
            await page.wait_for_timeout(100)
            status_pill = page.locator("button[data-cycle=status]").first
        print("status cycle:", vals2)

        # dark mode check
        await page.emulate_media(color_scheme="dark")
        await page.wait_for_timeout(200)
        await page.screenshot(path=f"{BASE}/shots/7_dark.png", full_page=False)

        await browser.close()

asyncio.run(main())
