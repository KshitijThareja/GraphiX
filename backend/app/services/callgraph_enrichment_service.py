def enrich_django(callgraph: dict) -> dict:
    for node in callgraph["nodes"]:
        if "views." in node["id"]:
            node["framework"] = "django"
            node["type"] = "view"
            if node["id"].endswith("View"):
                node["tags"] = ["class-based-view"]
            elif "api_" in node["id"]:
                node["tags"] = ["api-view"]
    return callgraph

def enrich_flask(callgraph: dict) -> dict:
    for node in callgraph["nodes"]:
        if "routes." in node["id"] or "blueprints." in node["id"]:
            node["framework"] = "flask"
            node["type"] = "route"
            if "get_" in node["id"]:
                node["tags"] = ["http-get"]
            elif "post_" in node["id"]:
                node["tags"] = ["http-post"]
    return callgraph