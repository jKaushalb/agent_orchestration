import asyncio
import os
from tavily import AsyncTavilyClient
from dotenv import load_dotenv
from ddgs import DDGS
import json
import wikipediaapi

load_dotenv()
wiki = wikipediaapi.Wikipedia(user_agent="my-project/1.0", language="en")
async_tavily_client = AsyncTavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))


async def web_search(query: str):
    """Web search for the given query string it will return list of title and content of first few pages"""

    response = await async_tavily_client.search(query)
    return json.dumps(response["results"])


def web_search2(query: str, max_results: int = 5):
    """Web search for the given query string it will return list of title and content of first few pages"""
    results = DDGS().text(query, max_results=max_results)
    return json.dumps([{"title": r["title"], "content": r["body"]} for r in results])


def wikipedia_extract(query: str):
    """Extracts the wikipedia page for the given query"""

    page = wiki.page(query)
    return json.dumps(
        {
            "title": page.title,
            "summary": page.summary if page.summary else "Page not found",
        }
    )

def write_tool(file_name:str, data:str):
    """ write the  data to the disk """

    try:
        # if ".txt" not in file_name:
        #     file_name += ".txt"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(data)

        return json.dumps({"status":"success"})
    except Exception as e:
        print("Exception ", e)
        return json.dumps({"status":"failure"}) 


TOOL_REGISTRY = {
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Get's the results of the first few pages",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "query to search",
                    }
                },
                "required": ["query"],
            },
        }
    },
    "web_search2": {
        "type": "function",
        "function": {
            "name": "web_search2",
            "description": "Web search for the given query string. It will return a list containing the title and text content of the first few pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string to look up on the web.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "The maximum number of search results to return. Defaults to 5.",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        }
    },
    "wikipedia_extract": {
        "type": "function",
        "function": {
            "name": "wikipedia_extract",
            "descrition": "Extracts the wikipedia page summary for the given query ",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "wikipedia page to look for.",
                    }
                },
            },
            "required": ["query"],
        }
    },

    "write_tool" : {
        "type": "function",
        "function" : {
            "name" : "write_tool",
            "description"  : "writes the data to the given file name on the disk.",
            "parameters" : {
                "type" : "object",
                "properties" : {
                    "file_name": {
                        "type": "string",
                        "description": "name of the output file"
                    },

                    "data" : {
                        "type": "string",
                        "description": "string data to be written in the file."
                    }
                },
                "required": ["file_name", "data"]
            }
        }
    }
}


TOOLS_to_FUNCTION = {
    "web_search": web_search,
    "web_search2": web_search2,
    "wikipedia_extract": wikipedia_extract,
    "write_tool": write_tool


}