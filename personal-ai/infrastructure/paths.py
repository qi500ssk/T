"""新安装默认使用当前系统用户的数据目录；开发者可显式指定独立目录。"""
import os
import sys
from pathlib import Path


def data_path(name: str) -> str:
    configured = os.environ.get("PERSONAL_AI_DATA_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "PersonalAI"
    elif sys.platform == "darwin":
        root = Path.home() / "Library/Application Support/PersonalAI"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "personal-ai"
    return str(root / name)
