import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_lock = threading.Lock()


def data_dir(name: str) -> str:
    file_path = os.path.join(ROOT, "data", name)
    os.makedirs(file_path, exist_ok=True)
    return file_path


def read_json(file_path: str, default=None):
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {} if default is None else default


def write_json(file_path: str, data) -> bool:
    tmp_path = file_path + ".tmp"
    with _lock:
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, file_path)
            return True
        except OSError:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False
