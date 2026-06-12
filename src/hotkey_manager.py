"""Global hotkey handling using pynput"""

import json
import os
from pynput import keyboard
from typing import Callable, Dict


class HotkeyManager:
    """Register and manage global hotkeys"""

    def __init__(self):
        self.hotkeys = {}
        self.listener = None
        self._load_hotkeys()

    def _load_hotkeys(self):
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "hotkeys.json"
        )
        with open(config_path) as f:
            self.hotkeys = json.load(f)

    def register_hotkeys(self, callbacks: Dict[str, Callable]):
        hotkey_map = {}
        for action, hotkey_str in self.hotkeys.items():
            if action in callbacks:
                hotkey_map[hotkey_str] = callbacks[action]

        if hotkey_map:
            self.listener = keyboard.GlobalHotKeys(hotkey_map)
            self.listener.start()
            print(f"✓ Registered {len(hotkey_map)} global hotkeys")

    def unregister_hotkeys(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
            print("✓ Unregistered global hotkeys")

    def update_hotkey(self, action: str, new_hotkey: str):
        self.hotkeys[action] = new_hotkey
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "hotkeys.json"
        )
        with open(config_path, "w") as f:
            json.dump(self.hotkeys, f, indent=4)