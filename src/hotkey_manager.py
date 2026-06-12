"""Global hotkey handling using pynput"""

import json
import os
import sys
from pynput import keyboard
from typing import Callable, Dict


def _base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.join(os.path.dirname(__file__), "..")


class HotkeyManager:

    def __init__(self):
        self.hotkeys = {}
        self.listener = None
        self._load_hotkeys()

    def _load_hotkeys(self):
        with open(os.path.join(_base_dir(), "config", "hotkeys.json")) as f:
            self.hotkeys = json.load(f)

    def register_hotkeys(self, callbacks: Dict[str, Callable]):
        hotkey_map = {
            hotkey_str: callbacks[action]
            for action, hotkey_str in self.hotkeys.items()
            if action in callbacks
        }
        if hotkey_map:
            self.listener = keyboard.GlobalHotKeys(hotkey_map)
            self.listener.start()
            print(f"✓ Registered {len(hotkey_map)} global hotkeys")

    def unregister_hotkeys(self):
        if self.listener:
            self.listener.stop()
            self.listener = None

    def update_hotkey(self, action: str, new_hotkey: str):
        self.hotkeys[action] = new_hotkey
        path = os.path.join(_base_dir(), "config", "hotkeys.json")
        with open(path, "w") as f:
            json.dump(self.hotkeys, f, indent=4)
