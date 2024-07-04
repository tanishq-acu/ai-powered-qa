import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async


async def main():
    async with async_playwright() as p:
        # launch the browser
        browser = await p.chromium.launch()
        # open a new page
        page = await browser.new_page()

        # register the Playwright Stealth plugin
        await stealth_async(page)

        # visit the target page
        await page.goto("https://arh.antoinevastel.com/bots/areyouheadless")

        # extract the message contained on the page
        message_element = page.locator("#res")
        message = await message_element.text_content()

        # print the resulting message
        print(f'The result is: "{message}"')

        # close the browser and release its resources
        await browser.close()


asyncio.run(main())
