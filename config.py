import json
from typing import Any
import shlex
class Config:
    def __init__(self, path="config.json"):
        self.path = path
        self._data = self._load()

    def _load(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)
        
    def _save(self, data: dict = None):
        data = self._data if data is None else data
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    
    def _reload(self):
        self._data = self._load()

    def get(self, section, key):
        return self._data.get(section, {}).get(key)

    @property
    def chat_id(self):
        return self._data["credits"]["CHAT_ID"]

    @property
    def token(self):
        return self._data["credits"]["TELEGRAM_TOKEN"]

    @property
    def poll_interval(self):
        return self._data["attributes"]["POLL_INTERVAL"]

    @property
    def pnl_min(self):
        return self._data["attributes"]["PNL_MIN"]

    @property
    def min_position_size(self):
        return self._data["attributes"]["MIN_POSITION_SIZE"]

    @property
    def winrate_min(self):
        return self._data["attributes"]["WINRATE_MIN"]
    @property
    def min_trades(self):
        return self._data["attributes"]["MIN_TRADES"]
    @property
    def min_roi(self):
        return float(self._data["attributes"]["MIN_ROI"])
    @property
    def period(self):
        return self._data["attributes"]["PERIOD"]
    

    def attributes_keys(self):
        return set(self._data.get("attributes", {}).keys())

    def set_attribute(self, key: str, value: Any):
        attrs = self._data.setdefault("attributes", {})
        # Преобразование типов: пытаемся подстроиться под текущий тип, если есть
        if key in attrs:
            current = attrs[key]
            try:
                if isinstance(current, bool):
                    # интерпретируем "true"/"false"
                    if isinstance(value, str):
                        value_parsed = value.lower() in ("1", "true", "yes", "on")
                    else:
                        value_parsed = bool(value)
                elif isinstance(current, int):
                    value_parsed = int(value)
                elif isinstance(current, float):
                    value_parsed = float(value)
                else:
                    value_parsed = value
            except Exception:
                # fallback: оставим строку
                value_parsed = value
        else:
            # если ключ новый — сохраняем как строку или число если возможно
            try:
                if isinstance(value, str) and value.isdigit():
                    value_parsed = int(value)
                else:
                    value_parsed = float(value)
            except Exception:
                value_parsed = value

        attrs[key] = value_parsed
        self._save()

    def delete_attribute(self, key: str):
        attrs = self._data.get("attributes", {})
        if key in attrs:
            del attrs[key]
            self._save()
