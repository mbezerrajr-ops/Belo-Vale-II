import asyncio
from playwright.async_api import async_playwright

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        context = await browser.new_context(viewport={"width": 1400, "height": 1000})
        page = await context.new_page()
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", "belovale2026")
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(300)
        await page.click("#btnFormBranco")
        await page.wait_for_timeout(200)

        async with context.expect_page() as new_page_info:
            await page.click("#mGo")
        new_page = await new_page_info.value
        await new_page.wait_for_load_state()
        title = await new_page.title()
        rows = await new_page.locator("table tbody tr").count()
        print("print window title:", title)
        print("print window rows:", rows)
        await new_page.screenshot(path=f"{BASE}/shots/8_print_output.png", full_page=True)
        await browser.close()

asyncio.run(main())
