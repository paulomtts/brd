import dataclasses
import json


def ok_envelope(data) -> dict:
    return {"ok": True, "data": data}


def error_envelope(error_type: str, message: str) -> dict:
    return {"ok": False, "error": {"type": error_type, "message": message}}


def _json_default(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    raise TypeError(f"object of type {type(obj)} is not JSON serializable")


def render_tree_text(nodes: list[dict], _prefix: str = "") -> str:
    lines = []
    for index, node in enumerate(nodes):
        is_last = index == len(nodes) - 1
        connector = "└── " if is_last else "├── "
        branch = "" if _prefix == "" else _prefix
        lines.append(f"{branch}{connector}{node['title']} [{node['status']}] ({node['id']})")
        if node["children"]:
            child_prefix = _prefix + ("    " if is_last else "│   ")
            lines.append(render_tree_text(node["children"], child_prefix))
    return "\n".join(lines)


def _render_pretty(envelope: dict) -> str:
    if not envelope["ok"]:
        error = envelope["error"]
        return f"Error ({error['type']}): {error['message']}"

    data = envelope["data"]
    if isinstance(data, list) and all(isinstance(item, dict) and "title" in item for item in data):
        return "\n".join(
            f"{item['id']}  [{item.get('status', '')}]  {item['title']}" for item in data
        )
    return str(data)


def print_result(envelope: dict, pretty: bool) -> None:
    if pretty:
        print(_render_pretty(envelope))
    else:
        print(json.dumps(envelope, default=_json_default))
