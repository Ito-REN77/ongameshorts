"""JSON config loading/saving with defaults merged in."""
import json
import os
from copy import deepcopy

DEFAULTS = {
    "onboarding_shown": False,
    "compact_style": True,
    "hide_video_ui": True,
    "show_info_panels": True,
    "volume": 80,
    "autoplay": True,
    "window": {
        "width": 600,
        "height": 340,
        "x": None,
        "y": None,
        "margin_bottom": 4,
    },
    "hotkeys": {
        "toggle_play_pause": {"modifiers": ["ctrl", "alt"], "key": "P"},
        "next_short": {"modifiers": ["ctrl", "alt"], "key": "N"},
        "toggle_window": {"modifiers": ["ctrl", "alt"], "key": "H"},
        "open_settings": {"modifiers": ["ctrl", "alt"], "key": "S"},
        "toggle_info_panels": {"modifiers": ["ctrl", "alt"], "key": "I"},
        "open_interact_window": {"modifiers": ["ctrl", "alt"], "key": "O"},
    },
}


def _deep_merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    def __init__(self, path="config.json"):
        self.path = os.path.abspath(path)
        self.data = deepcopy(DEFAULTS)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            self.data = _deep_merge(DEFAULTS, on_disk)
        else:
            self.data = deepcopy(DEFAULTS)
            self.save()
        return self.data

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, *keys, default=None):
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, *keys_and_value):
        *keys, value = keys_and_value
        node = self.data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
