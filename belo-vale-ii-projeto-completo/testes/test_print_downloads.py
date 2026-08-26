import asyncio, json
from playwright.async_api import async_playwright

BASE = "/tmp/claude-0/-home-user-Balancetes-porto/6cc42e22-5678-5e79-9cba-4f9e401567a5/scratchpad/leo_figueiroa"

MOCK_CLAUDE_OK = """
window.claude = {
  __saveCalls: [],
  use: async function(name) {
    if (name === "artifact") return { publish: async () => {} };
    if (name === "downloads") {
      return {
        save: async (req) => {
          window.claude.__saveCalls.push({ filename: req.filename, dataLen: (req.data || "").length, dataSample: (req.data || "").slice(0, 300) });
          return { status: "saved" };
        }
      };
    }
    return null;
  }
};
"""

MOCK_CLAUDE_DECLINED = """
window.claude = {
  use: async function(name) {
    if (name === "artifact") return { publish: async () => {} };
    if (name === "downloads") {
      return { save: async () => { const e = new Error("declined"); e.code = "declined"; throw e; } };
    }
    return null;
  }
};
"""

MOCK_CLAUDE_HTML_NOT_ENABLED = """
window.claude = {
  __saveCalls: [],
  use: async function(name) {
    if (name === "artifact") return { publish: async () => {} };
    if (name === "downloads") {
      return {
        save: async (req) => {
          if (req.filename.endsWith(".html")) { const e = new Error("extension_not_enabled"); e.code = "extension_not_enabled"; throw e; }
          window.claude.__saveCalls.push({ filename: req.filename, dataSample: (req.data || "").slice(0, 200) });
          return { status: "saved" };
        }
      };
    }
    return null;
  }
};
"""

MOCK_CLAUDE_NONE = "window.claude = undefined;"

async def run_scenario(name, init_script):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        popups = []
        page.on("popup", lambda p2: popups.append(p2))
        await page.add_init_script(init_script)
        await page.goto(f"file://{BASE}/platform_v3.html")
        await page.fill("#loginEmail", "mbezerrajr@gmail.com")
        await page.fill("#loginPass", "belovale2026")
        await page.click("#loginForm button[type=submit]")
        await page.wait_for_timeout(400)
        await page.click("button[data-tab=vacas]")
        await page.wait_for_timeout(200)
        await page.click("#btnImprimirLista")
        await page.wait_for_timeout(150)
        await page.click("#mGo")
        await page.wait_for_timeout(400)
        toast_class = await page.get_attribute("#bv2Toast", "class")
        toast_text = await page.inner_text("#bv2Toast")
        save_calls = await page.evaluate("window.claude && window.claude.__saveCalls ? window.claude.__saveCalls : null")
        print(f"--- {name} ---")
        print("toast class:", toast_class)
        print("toast text:", toast_text)
        print("save calls:", json.dumps(save_calls, ensure_ascii=False)[:500] if save_calls else save_calls)
        print("popups:", len(popups), "errors:", errors)
        await browser.close()

async def main():
    await run_scenario("OK (html accepted)", MOCK_CLAUDE_OK)
    await run_scenario("declined", MOCK_CLAUDE_DECLINED)
    await run_scenario("html not enabled -> csv fallback", MOCK_CLAUDE_HTML_NOT_ENABLED)
    await run_scenario("no window.claude at all", MOCK_CLAUDE_NONE)

asyncio.run(main())
