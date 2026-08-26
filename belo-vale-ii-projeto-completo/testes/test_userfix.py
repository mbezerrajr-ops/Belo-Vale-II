import asyncio
from playwright.async_api import async_playwright

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

async def main():
    errors = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("pageerror", lambda exc: errors.append(f"PAGEERROR: {exc}"))
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", "belovale2026")
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)
        await page.click("button[data-tab=usuarios]")
        await page.wait_for_timeout(300)

        # edit nome of Leonardo
        nome_span = page.locator("tr[data-id=u2] .ed-text[data-field=nome]")
        await nome_span.dblclick()
        await page.wait_for_timeout(150)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("Leonardo Silva")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)
        nome_after = await page.locator("tr[data-id=u2] td").nth(0).inner_text()
        print("nome after edit:", nome_after)

        # edit email of Leonardo
        email_span = page.locator("tr[data-id=u2] .ed-text[data-field=email]")
        await email_span.dblclick()
        await page.wait_for_timeout(150)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("leonardo.silva@belovale.com")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(300)
        email_after = await page.locator("tr[data-id=u2] td").nth(1).inner_text()
        print("email after edit:", email_after)

        # try duplicate email (should alert and revert)
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        email_span2 = page.locator("tr[data-id=u2] .ed-text[data-field=email]")
        await email_span2.dblclick()
        await page.wait_for_timeout(150)
        await page.keyboard.press("Control+A")
        await page.keyboard.type("mbezerrajr@gmail.com")
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(400)
        email_after2 = await page.locator("tr[data-id=u2] td").nth(1).inner_text()
        print("email after duplicate attempt (should be unchanged):", email_after2)

        # test login with new email works
        await page.click("#logoutBtn")
        await page.wait_for_timeout(300)
        await page.fill("#loginEmail", "leonardo.silva@belovale.com")
        await page.fill("#loginPass", "belovale2026")
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)
        visible = await page.is_visible("#app")
        who = await page.inner_text("#whoLabel")
        print("login with updated email works:", visible, who)

        print("ERRORS:", errors)
        await browser.close()

asyncio.run(main())
