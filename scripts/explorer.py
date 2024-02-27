from dataclasses import dataclass, field
from inspect import cleandoc
import json
import logging
import random
import time

import numpy as np
from openai import OpenAI
from openai.types.chat.chat_completion_tool_param import ChatCompletionToolParam

from ai_powered_qa.custom_plugins.playwright_plugin.html_paging import (
    PlaywrightPluginHtmlPaging,
)


@dataclass
class Website:
    urls: list[str]
    title: str
    description: str
    embedding: np.ndarray
    actions: list[str] = field(default_factory=list)


logging.basicConfig(level=logging.INFO)


def accept_cookies_if_present(client: OpenAI, plugin: PlaywrightPluginHtmlPaging):
    html = plugin._run_async(plugin._get_page_content())
    has_cookies = False
    _, no_parts = plugin._get_html_part(html)

    prompt_has_cookies = """
        You are an expert on HTML. You are given a website HTML and you are
        asked to check if the website shows a cookie consent banner.

        Here is the current HTML:

        ----- HTML START -----
        {html_part}
        ----- HTML END -----

        Does the website show a cookie consent banner? Answer with 'yes' or 'no'.
    """

    for i in range(1, no_parts + 1):
        plugin._part = i
        html_part, _ = plugin._get_html_part(html)
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {
                    "role": "user",
                    "content": prompt_has_cookies.format(html_part=html_part),
                }
            ],
            temperature=0.1,
        )
        response = completion.choices[0].message.content
        if response and "yes" in response.lower():
            has_cookies = True
            break

    if has_cookies:
        logging.info("Website has cookies.")
        execute_action(client, plugin, "Click on the buttom for accepting cookies")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def find_similar(websites: list[Website], current: Website) -> Website | None:
    similarities = [cosine_similarity(w.embedding, current.embedding) for w in websites]
    logging.info(current.urls[0])
    for i, sim in enumerate(similarities):
        logging.info(f"Similarity with {websites[i].urls[0]}: {sim}")
    max_similarity_idx = np.argmax(similarities)
    max_similarity = similarities[max_similarity_idx]
    if max_similarity > 0.92:
        return websites[max_similarity_idx]
    return None


def description_to_string(description: dict) -> str:
    elements = "\n".join(
        f"{e['type']}: {e['description']}" for e in description["interactive_elements"]
    )
    return f"""
        Basic purpose: {description['basic_purpose']}

        Interactive elements: 
        {elements}
        """


def execute_action(
    client: OpenAI, plugin: PlaywrightPluginHtmlPaging, action: str
) -> bool:
    prompt_execute = cleandoc(
        f"""
        You are an expert on executing action on the web. You are given
        a website HTML, it's short text description and an action to perform

        If a tool requires a selector, the selector has to be
        compatible with Playwright and the element should be present
        in HTML.

        Here is the current context:

        {plugin.context_message}

        The recommended action is:

        {action}
        """
    )

    completion = client.chat.completions.create(
        model="gpt-3.5-turbo-0125",
        messages=[
            {"role": "system", "content": plugin.system_message},
            {"role": "user", "content": prompt_execute},
        ],
        tools=plugin.tools,
        temperature=0.2,
    )

    tool_calls = completion.choices[0].message.tool_calls
    if tool_calls and len(tool_calls) > 0:
        tool_to_call = tool_calls[0].function
        tool_name = tool_to_call.name
        tool_args = json.loads(tool_to_call.arguments)
        logging.info(f"Executing tool: {tool_name} with arguments: {tool_args}")
        plugin.call_tool(tool_name, **tool_args)
        return True

    return False


def main():
    websites_visited: list[Website] = []
    domain = "czc.cz"
    start_url = f"https://{domain}"

    client = OpenAI()
    plugin = PlaywrightPluginHtmlPaging(name="playwright", client=client)
    plugin.navigate_to_url(start_url)
    time.sleep(5)
    accept_cookies_if_present(client, plugin)

    for _ in range(10):
        time.sleep(3)
        plugin._part = 1
        html = plugin.html
        title = plugin.title
        url = plugin._page.url if plugin._page else None

        if url and domain not in url:
            logging.info(f"Left the domain of {domain}. Navigating back to the start")
            plugin.navigate_to_url(start_url)
            continue

        prompt_description = cleandoc(
            f"""
            Analyze the following HTML and provide a specific and  extensive 
            description of its contents. Imagine you are describing the page
            to a person who cannot see it.

            The description should list interactive elements, such as links, 
            buttons or forms. It should also explain the specific purpose of
            the page and its content. When describing the content, think about
            the specific subpage you are visiting instead the whole web portal.
            
            Each element should be represented by a separate record:

            INCORRECT EXAMPLE:
            Links to specific categories like 'Oblíbené inzeráty', 'Moje inzeráty', and 'Přidat inzerát'

            CORRECT EXAMPLE:
            Link to the category 'Oblíbené inzeráty' - A link to the user's favorite ads
            Link to the category 'Moje inzeráty' - A link to the user's ads
            Link to the category 'Přidat inzerát' - A link to the form for adding a new ad

            Title: {title}

            {html}
            """
        )

        describe_function: ChatCompletionToolParam = {
            "type": "function",
            "function": {
                "name": "describe_html",
                "description": "Describe the subpage from its HTML",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "basic_purpose": {
                            "type": "string",
                            "description": "Top level description of the subpage's purpose. E.g. 'This is a form for adding a new user'",
                        },
                        "interactive_elements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "description": "Type of the interactive element. E.g. 'link', 'button'",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Description of the interactive element. E.g. 'A link to the homepage'",
                                    },
                                },
                            },
                            "description": "List of interactive elements on the page. E.g. 'A link to the homepage'",
                        },
                    },
                },
            },
        }

        completion = client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[{"role": "user", "content": prompt_description}],
            tools=[describe_function],
            tool_choice={"type": "function", "function": {"name": "describe_html"}},
            temperature=0.1,
        )

        tool_calls = completion.choices[0].message.tool_calls
        if not tool_calls or len(tool_calls) == 0:
            logging.error("No description tool called.")
            break

        description = json.loads(tool_calls[0].function.arguments)
        description = description_to_string(description)
        logging.info(f"Description generated:\n {description}")

        response = client.embeddings.create(model="text-embedding-3-small", input=html)
        embedding = np.array(response.data[0].embedding)
        website_current = Website([url] if url else [], title, description, embedding)

        if len(websites_visited) > 0:
            website_similar = find_similar(websites_visited, website_current)
            if website_similar:
                logging.info(f"Found similar website: {website_similar.urls[0]}")
                website_current = website_similar
                if url and url not in website_current.urls:
                    website_current.urls.append(url)
            else:
                websites_visited.append(website_current)
        else:
            websites_visited.append(website_current)

        prompt_recommend = cleandoc(
            f"""
            You are a web crawler. Your goal is to analyze the textual 
            description of a webpage provided to you and recommend a next 
            action to perform to explore a given website further and learn
            about it as much as possible.

            You can perform one of the following actions:
            - Click on a link or button

            Here is the textual description of the current page:

            URL: {url}
            Title: {title}

            {description}

            Here is the list of actions you have alread performed on
            this subpage, avoid repeating them:

            {str(website_current.actions)}

            Please recommend 3 actions to perform next and explain the
            reasoning behind your recommendation.
            """
        )

        recommend_actions_tool: ChatCompletionToolParam = {
            "type": "function",
            "function": {
                "name": "recommend_actions",
                "description": "Recommend actions to perform next",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "description": "Recommended action to perform next",
                            },
                        }
                    },
                },
            },
        }

        completion = client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[{"role": "user", "content": prompt_recommend}],
            tools=[recommend_actions_tool],
            temperature=0.1,
            tool_choice={"type": "function", "function": {"name": "recommend_actions"}},
        )

        tool_calls = completion.choices[0].message.tool_calls
        if not tool_calls or len(tool_calls) == 0:
            logging.error("No recommendation tool called.")
            break

        recommendations = json.loads(tool_calls[0].function.arguments)

        if "actions" not in recommendations or len(recommendations["actions"]) == 0:
            logging.info("No recommendations generated. Navigating back to the start")
            plugin.navigate_to_url(start_url)

        recommendation = random.choice(recommendations["actions"])
        logging.info(f"Recommended action: {recommendation}")
        executed = execute_action(client, plugin, recommendation)
        if executed:
            website_current.actions.append(recommendation)

    plugin.close()
    print("Exploration finished.")
    print("Websites visited:")

    for w in websites_visited:
        print(w.urls)
        print(w.description)
        print(w.actions)
        print("--------")


if __name__ == "__main__":
    main()
