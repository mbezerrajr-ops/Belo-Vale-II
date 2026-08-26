import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        page = await browser.new_page(viewport={"width":1320,"height":1000}, color_scheme="dark")
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        await page.goto('file:///tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa/full2.html')
        await page.wait_for_timeout(500)
        await page.click('#segLote button[data-value="LOTE 2"]')
        await page.wait_for_timeout(300)
        await page.screenshot(path='v4_dark_lote2.png', full_page=False)
        print("ERRORS:", errors)
        await browser.close()

asyncio.run(main())
