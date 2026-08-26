import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        page = await browser.new_page(viewport={"width":1280,"height":900}, color_scheme="dark")
        await page.goto('file:///tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa/full.html')
        await page.wait_for_timeout(600)
        await page.screenshot(path='shot_dark.png', full_page=False)
        await browser.close()

asyncio.run(main())
