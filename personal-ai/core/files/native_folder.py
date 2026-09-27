"""Trusted local folder selection; the HTTP caller cannot supply a grant path."""
import base64
import ctypes
import subprocess
import sys
import threading
import time
from pathlib import Path

_picker_lock = threading.Lock()
_process_lock = threading.Lock()
_active: dict[str, subprocess.Popen] = {}
_cancelled: dict[str, float] = {}


def select_local_folder(request_id: str = "default") -> str | None:
    if sys.platform != "win32":
        raise ValueError("当前本机文件夹选择仅支持 Windows")
    source = base64.b64encode(Path(__file__).with_name("FolderPicker.cs").read_bytes()).decode("ascii")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    owner = user32.GetForegroundWindow() or 0
    with _process_lock:
        if request_id in _cancelled:
            _cancelled.pop(request_id, None)
            return None
    if not _picker_lock.acquire(blocking=False):
        raise ValueError("文件夹选择窗口已打开，请先完成选择")
    script = """$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__SOURCE__')))
$path = [ProjectFolderPicker]::Select([IntPtr]::new(__OWNER__))
if ($path) {
  [Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($path)))
}
""".replace("__SOURCE__", source).replace("__OWNER__", str(owner))
    try:
        process = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-STA", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        with _process_lock:
            if request_id in _cancelled:
                process.terminate()
            else:
                _active[request_id] = process
        # The child creates UI for a user click in the foreground browser.
        user32.AllowSetForegroundWindow(process.pid)
        try:
            stdout, _ = process.communicate(timeout=240)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise ValueError("文件夹选择超时，请重试")
        if process.returncode:
            with _process_lock:
                if request_id not in _active:
                    return None  # Explicit cancellation from the page.
            raise ValueError("无法打开文件夹窗口，请重试")
        return base64.b64decode(stdout.strip(), validate=True).decode("utf-8") if stdout.strip() else None
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("无法完成文件夹选择，请重新打开选择窗口") from exc
    finally:
        with _process_lock:
            _active.pop(request_id, None)
            _cancelled.pop(request_id, None)
        _picker_lock.release()


def cancel_local_folder(request_id: str) -> None:
    with _process_lock:
        now = time.monotonic()
        for key in list(_cancelled):
            if now - _cancelled[key] > 300:
                del _cancelled[key]
        _cancelled[request_id] = now
        process = _active.pop(request_id, None)
        if process is not None and process.poll() is None:
            process.terminate()
