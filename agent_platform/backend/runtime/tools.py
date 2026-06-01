"""Tool catalog for the agent runtime.

Two parallel dicts that MUST stay aligned (the pattern lifted from the
prototype): ``TOOL_REGISTRY`` (OpenAI-style JSON schema sent to the model) and
``TOOLS_TO_FUNCTION`` (name -> Python callable). An agent's ``tools`` list is a
list of string keys into both.

Changes vs the prototype:
- web_search2: honours its ``query`` argument (the prototype hardcoded
  "python programming").
- wikipedia_extract: schema fixed (``required`` inside ``parameters``, typo
  ``descrition`` -> ``description``); returns summary + first sections.
- fetch_url (new): fetch a page and return cleaned readable text.
- read_file / write_file / list_files: confined to a sandboxed workspace dir.

All tools are synchronous so the runner's tool loop stays simple.
"""
import json
import os
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# --- sandbox -----------------------------------------------------------------
WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"
WORKSPACE.mkdir(exist_ok=True)


def _safe_path(file_name: str) -> Path:
    """Resolve file_name inside WORKSPACE, rejecting traversal outside it."""
    p = (WORKSPACE / file_name).resolve()
    if WORKSPACE not in p.parents and p != WORKSPACE:
        raise ValueError("path escapes the workspace sandbox")
    return p


# --- web tools ---------------------------------------------------------------
def web_search(query: str, max_results: int = 5) -> str:
    """Tavily web search. Returns JSON list of {title, content, url}."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY"))
    resp = client.search(query, max_results=max_results)
    return json.dumps(
        [
            {"title": r.get("title"), "content": r.get("content"), "url": r.get("url")}
            for r in resp.get("results", [])
        ]
    )


def web_search2(query: str, max_results: int = 5) -> str:
    """DuckDuckGo web search (no API key). Returns JSON list of {title, content, url}."""
    from ddgs import DDGS

    results = DDGS().text(query, max_results=max_results)
    return json.dumps(
        [
            {"title": r.get("title"), "content": r.get("body"), "url": r.get("href")}
            for r in results
        ]
    )


def wikipedia_extract(query: str) -> str:
    """Return a Wikipedia page's summary plus its first sections."""
    import wikipediaapi

    wiki = wikipediaapi.Wikipedia(user_agent="agent-platform/1.0", language="en")
    page = wiki.page(query)
    if not page.exists():
        return json.dumps({"title": query, "summary": "Page not found"})
    sections = [
        {"title": s.title, "text": s.text[:1500]} for s in page.sections[:5]
    ]
    return json.dumps(
        {"title": page.title, "summary": page.summary, "sections": sections}
    )


def fetch_url(url: str, max_chars: int = 6000) -> str:
    """Fetch a URL and return cleaned, readable page text (scripts/styles stripped)."""
    try:
        resp = requests.get(
            url, timeout=15, headers={"User-Agent": "agent-platform/1.0"}
        )
        resp.raise_for_status()
    except Exception as e:  # network/HTTP failure -> structured error
        return json.dumps({"url": url, "error": str(e)})

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return json.dumps({"url": url, "text": text[:max_chars]})


# --- file tools (sandboxed) --------------------------------------------------
def write_file(file_name: str, data: str) -> str:
    """Write text to a file inside the workspace sandbox."""
    try:
        p = _safe_path(file_name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")
        return json.dumps({"status": "success", "path": str(p.relative_to(WORKSPACE))})
    except Exception as e:
        return json.dumps({"status": "failure", "error": str(e)})


def read_file(file_name: str) -> str:
    """Read a text file from the workspace sandbox."""
    try:
        p = _safe_path(file_name)
        return json.dumps({"status": "success", "content": p.read_text(encoding="utf-8")})
    except Exception as e:
        return json.dumps({"status": "failure", "error": str(e)})


def list_files() -> str:
    """List files in the workspace sandbox."""
    files = [str(p.relative_to(WORKSPACE)) for p in WORKSPACE.rglob("*") if p.is_file()]
    return json.dumps({"files": files})


# --- registries --------------------------------------------------------------
def _fn(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_QUERY = {"query": {"type": "string", "description": "the search query"}}
_MAXR = {
    "max_results": {
        "type": "integer",
        "description": "max number of results (default 5)",
    }
}

TOOL_REGISTRY = {
    "web_search": _fn(
        "web_search",
        "Search the web (Tavily). Returns a JSON list of {title, content, url}.",
        {**_QUERY, **_MAXR},
        ["query"],
    ),
    "web_search2": _fn(
        "web_search2",
        "Search the web (DuckDuckGo, no API key). Returns JSON list of {title, content, url}.",
        {**_QUERY, **_MAXR},
        ["query"],
    ),
    "wikipedia_extract": _fn(
        "wikipedia_extract",
        "Get a Wikipedia page's summary and first sections for a topic.",
        {"query": {"type": "string", "description": "the Wikipedia page title/topic"}},
        ["query"],
    ),
    "fetch_url": _fn(
        "fetch_url",
        "Fetch a web page and return its cleaned readable text. Use after a search to read a result in full.",
        {"url": {"type": "string", "description": "the page URL to fetch"}},
        ["url"],
    ),
    "write_file": _fn(
        "write_file",
        "Write text to a file in the workspace (e.g. save the final report).",
        {
            "file_name": {"type": "string", "description": "output file name"},
            "data": {"type": "string", "description": "text content to write"},
        },
        ["file_name", "data"],
    ),
    "read_file": _fn(
        "read_file",
        "Read a text file from the workspace.",
        {"file_name": {"type": "string", "description": "file name to read"}},
        ["file_name"],
    ),
    "list_files": _fn(
        "list_files",
        "List the files currently in the workspace.",
        {},
        [],
    ),
}

TOOLS_TO_FUNCTION = {
    "web_search": web_search,
    "web_search2": web_search2,
    "wikipedia_extract": wikipedia_extract,
    "fetch_url": fetch_url,
    "write_file": write_file,
    "read_file": read_file,
    "list_files": list_files,
}

# Names exposed to the CRUD/UI layer so agents can be configured with valid tools.
AVAILABLE_TOOLS = list(TOOL_REGISTRY.keys())
