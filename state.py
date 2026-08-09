import json
import os


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {"classes": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path: str, state: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def get_class_entry(state: dict, class_id: str) -> dict:
    return state["classes"].setdefault(class_id, {"notified_occurrences": []})
