import asyncio
from playwright.async_api import async_playwright

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", "belovale2026")
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(200)
        await page.evaluate("window.print = () => {};")
        await page.click("#btnImprimirLista")
        await page.wait_for_timeout(200)
        await page.click("#mGo")
        await page.wait_for_timeout(200)
        await page.emulate_media(media="print")
        await page.wait_for_timeout(150)
        await page.screenshot(path=f"{BASE}/shots/9_print_media.png", full_page=False)
        await browser.close()

asyncio.run(main())
