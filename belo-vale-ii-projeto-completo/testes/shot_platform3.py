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

        await page.click('button[data-tab="usuarios"]')
        await page.wait_for_timeout(200)
        await page.click('#addUserBtn')
        await page.wait_for_timeout(200)

        # set contenteditable values via real keyboard-like interaction
        async def set_ed(locator, text):
            await locator.click()
            await page.keyboard.press('Control+A')
            await page.keyboard.type(text)
            await locator.evaluate("el => el.blur()")

        rows = page.locator('#usersBody tr')
        last = rows.last
        eds = last.locator('.ed')
        await set_ed(eds.nth(0), 'Teste Usuario')
        await set_ed(eds.nth(1), 'teste@fazenda.com')
        await set_ed(eds.nth(2), 'senha123')

        # verify DOM content directly
        vals = await last.evaluate("tr => Array.from(tr.querySelectorAll('.ed')).map(e => e.textContent)")
        print("new user row content:", vals)

        await page.click('#logoutBtn')
        await page.wait_for_timeout(200)
        await page.fill('#loginEmail', 'teste@fazenda.com')
        await page.fill('#loginPass', 'senha123')
        await page.click('.login-btn')
        await page.wait_for_timeout(400)
        login_visible = await page.is_visible('#loginScreen')
        print("login screen visible after new-user login attempt:", login_visible)
        if not login_visible:
            who = await page.text_content('#whoLabel')
            print("Logged in as:", who)

        print("Errors so far:", errors)
        await browser.close()

asyncio.run(main())
