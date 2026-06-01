"""Smoke-test the Agent CRUD API end to end with FastAPI's TestClient.

Run from agent_platform/:  python -m backend.verify_crud
"""
from fastapi.testclient import TestClient

from .main import app


def main() -> None:
    # Context-manager form runs the lifespan handler -> init_db().
    with TestClient(app) as client:
        _run(client)


def _run(client: TestClient) -> None:
    # CREATE
    payload = {
        "name": "Researcher",
        "role": "researcher",
        "system_prompt": "Research the topic using your tools.",
        "model": "gemini/gemini-2.5-flash",
        "tools": ["web_search", "wikipedia_extract"],
        "channels": ["web"],
        "guardrails": {"max_cost_usd": 0.5},
    }
    r = client.post("/agents", json=payload)
    assert r.status_code == 201, r.text
    agent = r.json()
    aid = agent["id"]
    assert agent["tools"] == ["web_search", "wikipedia_extract"]
    print("CREATE ok ->", aid)

    # LIST
    r = client.get("/agents")
    assert r.status_code == 200 and any(a["id"] == aid for a in r.json())
    print("LIST   ok ->", len(r.json()), "agent(s)")

    # READ
    r = client.get(f"/agents/{aid}")
    assert r.status_code == 200 and r.json()["name"] == "Researcher"
    print("READ   ok")

    # UPDATE (partial)
    r = client.put(f"/agents/{aid}", json={"role": "lead", "temperature": 0.7})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "lead" and r.json()["temperature"] == 0.7
    assert r.json()["name"] == "Researcher"  # untouched
    print("UPDATE ok")

    # 404 path
    assert client.get("/agents/does-not-exist").status_code == 404
    print("404    ok")

    # DELETE
    assert client.delete(f"/agents/{aid}").status_code == 204
    assert client.get(f"/agents/{aid}").status_code == 404
    print("DELETE ok")

    print("\nAll CRUD checks passed.")


if __name__ == "__main__":
    main()
