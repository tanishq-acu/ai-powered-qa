import json

from playwright.async_api import async_playwright

from langchain_modules.toolkit import PlayWrightBrowserToolkit


async def get_browser():
    browser = await async_playwright().start()
    async_browser = await browser.chromium.launch(headless=False)
    return async_browser


async def get_tools(browser) -> list:
    async_browser = browser
    toolkit = PlayWrightBrowserToolkit.from_browser(async_browser=async_browser)
    tools = toolkit.get_tools()
    return tools


async def call_function(browser, json_function: json):
    tools = await get_tools(browser)
    name_to_tool_map = {tool.name: tool for tool in tools}

    tool = name_to_tool_map[json_function["name"]]
    function_arguments = json.loads(json_function["arguments"])
    function_response = await tool._arun(**function_arguments)
    return function_response