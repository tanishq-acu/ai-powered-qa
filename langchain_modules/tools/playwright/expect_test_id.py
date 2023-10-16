from __future__ import annotations

from typing import Type

from langchain.tools.playwright.base import BaseBrowserTool
from langchain.tools.playwright.utils import aget_current_page
from playwright.async_api import expect as async_expect
from pydantic import BaseModel, Field


class ExpectTestIdToolInput(BaseModel):
    """Input for ExpectTestIdTool."""
    test_id: str = Field(..., description="TestID what you expect to see.")


class ExpectTestIdTool(BaseBrowserTool):
    """Tool for checking expected testId."""
    name: str = "expect_test_id"
    description: str = "Check if expected testId is visible on the current web page."
    args_schema: Type[BaseModel] = ExpectTestIdToolInput

    @staticmethod
    def _run() -> str:
        """_run() isn't implemented, but is required to be defined."""
        return "_run() not implemented."

    async def _arun(self, test_id: str) -> str:
        """Use the tool."""
        if self.async_browser is None:
            raise ValueError(f"Asynchronous browser not provided to {self.name}")

        page = await aget_current_page(self.async_browser)

        try:
            element = page.get_by_test_id(test_id)
            await async_expect(element).to_be_visible()
        except Exception:
            return f"Unable to expect '{test_id}'."

        return f"TestID: , {test_id}, is visible on the current page."