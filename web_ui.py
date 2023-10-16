from logging_handler import LoggingHandler
from langchain.tools.convert_to_openai import format_tool_to_openai_function
from langchain.schema.messages import (
    AIMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
)
from langchain.chat_models import ChatOpenAI
from utils import amark_invisible_elements, strip_html_to_structure
from langchain.tools.playwright.utils import (
    aget_current_page,
)
from langchain_modules.toolkit import PlayWrightBrowserToolkit
import streamlit as st
import json
from dotenv import load_dotenv
import asyncio
import datetime
import os
from constants import llm_models, function_call_defaults

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


load_dotenv()


if "messages" not in st.session_state:
    st.session_state.messages = []
if "browser" not in st.session_state:
    st.session_state.browser = None
if "loop" not in st.session_state:
    st.session_state.loop = asyncio.get_event_loop()
if "user_message_content" not in st.session_state:
    st.session_state.user_message_content = ""
if "ai_message_content" not in st.session_state:
    st.session_state.ai_message_content = ""
if "ai_message_function_name" not in st.session_state:
    st.session_state.ai_message_function_name = ""
if "ai_message_function_arguments" not in st.session_state:
    st.session_state.ai_message_function_arguments = ""


@st.cache_data
def load_conversation_history(project_name, test_case):
    try:
        with open(
            f"projects/{project_name}/{test_case}/conversation_history.json", "r"
        ) as f:
            st.session_state.messages = json.load(f)
            return st.session_state.messages
    except:
        return []


@st.cache_resource
def get_tools():
    async_browser = st.session_state.browser
    toolkit = PlayWrightBrowserToolkit.from_browser(
        async_browser=async_browser)
    tools = toolkit.get_tools()
    return tools


@st.cache_resource
def get_llm(gpt_model, project_name, test_case):

    llm = ChatOpenAI(
        model=gpt_model,
        streaming=False,
        temperature=0,
        callbacks=[setup_logging_handler(project_name, test_case)]
    )
    return llm


@st.cache_resource
def setup_logging_handler(project_name, test_case):
    return LoggingHandler(project_name, test_case)


async def get_context_message(browser):
    page = await aget_current_page(browser)
    await amark_invisible_elements(page)

    html_content = await page.content()
    stripped_html = strip_html_to_structure(html_content)

    context_message = SystemMessage(
        content=(
            f"Here is the current state of the browser:\n"
            f"```\n"
            f"{stripped_html}\n"
            f"```\n"
        ),
    )
    return context_message


async def get_browser():
    from playwright.async_api import async_playwright

    browser = await async_playwright().start()
    async_browser = await browser.chromium.launch(headless=False)
    return async_browser


async def on_submit(name_to_tool_map):
    if st.session_state.user_message_content:
        st.session_state.messages.append(
            {
                "role": "user",
                "content": st.session_state.user_message_content,
            }
        )
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": st.session_state.ai_message_content,
            "additional_kwargs": {
                "function_call": {
                    "name": st.session_state.ai_message_function_name,
                    "arguments": st.session_state.ai_message_function_arguments,
                }
            }
            if st.session_state.ai_message_function_name
            else {},
        }
    )
    if st.session_state.ai_message_function_name:
        tool = name_to_tool_map[st.session_state.ai_message_function_name]
        function_arguments = json.loads(
            st.session_state.ai_message_function_arguments)
        function_response = await tool._arun(
            **function_arguments,
        )
        st.session_state.messages.append(
            {
                "role": "function",
                "name": st.session_state.ai_message_function_name,
                "content": function_response,
            }
        )
    st.session_state.user_message_content = ""
    st.session_state.ai_message_content = ""
    st.session_state.ai_message_function_name = ""
    st.session_state.ai_message_function_arguments = ""


def run_on_submit(name_to_tool_map):
    # reset the options, unpredicateable behaviour otherwise
    st.session_state.function_call_option = function_call_defaults[0]
    st.session_state.gpt_model = llm_models[0]
    asyncio.set_event_loop(st.session_state.loop)
    return st.session_state.loop.run_until_complete(on_submit(name_to_tool_map))


def save_conversation_history(project_name: str, test_case: str):
    path = f"conversation_history/{project_name}/{test_case}"
    start_time = datetime.datetime.now().strftime("%Y_%m_%d-%H:%M:%S")
    file_path = os.path.join(path, f"{test_case}_history_{start_time}.json")

    if not os.path.exists(path):
        os.makedirs(path)

    with open(file_path, 'w') as f:
        f.write(json.dumps(st.session_state.messages, indent=4))


@st.cache_data
def get_function_call_options(functions):
    options = function_call_defaults
    options.extend([func["name"] for func in functions])

    return options


async def main():

    # Initialize browser
    if st.session_state.browser is None:
        st.session_state.browser = await get_browser()
    async_browser = st.session_state.browser

    # Get project and test case name
    project_name = st.text_input("Project name")
    test_case = st.text_input("Test case name")
    if not (project_name and test_case):
        st.cache_resource.clear()  # reset cache
        st.cache_data.clear()
        st.stop()

    # Load conversation file
    load_conversation_history(project_name, test_case)

    # System message
    with st.chat_message("system"):
        system_message = st.text_area(
            "System message",
            "You are a QA engineer controlling a browser. Your goal is to plan and go through a test scenario with the user.",
            key="system_message",
            label_visibility="collapsed",
        )

    # History for prompt
    prompt_messages = [SystemMessage(content=system_message)]
    for message in st.session_state.messages[-10:]:
        if message["role"] == "function":
            prompt_messages.append(FunctionMessage(**message))
            with st.chat_message("function"):
                st.subheader(message["name"])
                st.write(message["content"])
        elif message["role"] == "assistant":
            prompt_messages.append(AIMessage(**message))
            with st.chat_message("system"):
                st.write(message["content"])
                function_call = message.get("function_call", None)
                if function_call:
                    with st.status(function_call["name"], state="complete"):
                        st.write(function_call["arguments"])
        elif message["role"] == "user":
            prompt_messages.append(HumanMessage(**message))
            with st.chat_message("user"):
                st.write(message["content"])

    # Check last message
    last_message = None
    if st.session_state.messages:
        last_message = st.session_state.messages[-1]

    # User message
    if last_message == None or last_message["role"] == "assistant":
        with st.form("user_message"):
            st.form_submit_button(
                "Save conversation history",
                on_click=save_conversation_history,
                args=(project_name, test_case),
            )
        with st.chat_message("user"):
            user_message_content = st.text_area(
                "User message content",
                "Let's write a test for a chat app. We should test a user can send a message.",
                key="user_message_content",
                label_visibility="collapsed",
            )
            if user_message_content:
                prompt_messages.append(HumanMessage(
                    content=user_message_content))
            else:
                st.stop()

    # Context message

    context_message = await get_context_message(async_browser)
    with st.chat_message("system"):
        st.write(context_message.content)
    prompt_messages.append(context_message)

    tools = get_tools()
    functions = [format_tool_to_openai_function(t) for t in tools]
    name_to_tool_map = {tool.name: tool for tool in tools}

    # Call LLM

    col1, col2 = st.columns(2)
    with col1:
        function_call_option = st.selectbox(
            "Force function call?", get_function_call_options(functions), help="'auto' leaves the decision to the model,"
            " 'none' forces a generated message, or choose a specific function.", index=0, key="function_call_option")
    with col2:
        gpt_model = st.selectbox(
            "Change model?", llm_models, help="Change the llm. Be aware that gpt-4 is more expensive.",
            index=0, key="gpt_model")

    if function_call_option not in ["auto", "none"]:
        _function_call = {"name": function_call_option}
    else:
        _function_call = function_call_option

    st.write("Response is generated with model ", gpt_model,
             " and function call option ", _function_call, ".")
    llm = get_llm(gpt_model, project_name, test_case)

    response = llm(
        prompt_messages,
        functions=functions,
        function_call=_function_call,
    )

    st.session_state.ai_message_content = response.content
    function_call = response.additional_kwargs.get("function_call", None)
    if function_call:
        st.session_state.ai_message_function_name = function_call["name"]
        st.session_state.ai_message_function_arguments = function_call["arguments"]
    else:
        st.session_state.ai_message_function_name = ""
        st.session_state.ai_message_function_arguments = ""

    # AI message
    with st.chat_message("assistant"):
        with st.form("ai_message"):
            st.text_area(
                "AI message content",
                key="ai_message_content",
                label_visibility="collapsed",
            )
            function_call = response.additional_kwargs.get("function_call", {})
            st.text_input(
                "AI message function name",
                key="ai_message_function_name",
                label_visibility="collapsed",
            )
            st.text_area(
                "AI message function arguments",
                key="ai_message_function_arguments",
                label_visibility="collapsed",
            )
            st.form_submit_button(
                "Commit agent completion",
                on_click=lambda: run_on_submit(name_to_tool_map),
            )


if __name__ == "__main__":
    asyncio.set_event_loop(st.session_state.loop)
    st.session_state.loop.run_until_complete(main())