import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
        page = await browser.new_page(viewport={"width":1320,"height":1000})
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        with open('dashboard_v2.html', encoding='utf-8') as f:
            frag = f.read()
        full = f"<!doctype html><html><head><meta charset='utf-8'></head><body>{frag}</body></html>"
        with open('full2.html','w',encoding='utf-8') as f:
            f.write(full)
        await page.goto('file:///tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa/full2.html')
        await page.wait_for_timeout(500)

        await page.fill('#searchInput', 'gau')
        await page.wait_for_timeout(300)
        await page.screenshot(path='v3_search_gau.png', full_page=False)

        await page.click('#clearFilters')
        await page.click('#segSit button[data-value="VS"]')
        await page.wait_for_timeout(300)
        await page.screenshot(path='v3_secas.png', full_page=True)

        print("ERRORS:", errors)
        await browser.close()

asyncio.run(main())
