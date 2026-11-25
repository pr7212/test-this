import os
import random
import re
import subprocess
import time
import pyautogui
import pyperclip
import requests

try:
    import win32con
    import win32gui
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

STOP_FLAG = False

MIN_SPEED = 0.001
MAX_SPEED = 0.015

BOT_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_OLLAMA_MODEL = "llama3.2"


def resolve_ollama_model():
    """Use an explicitly selected Ollama model or discover one installed locally."""
    configured_model = os.getenv("CLEMOH_OLLAMA_MODEL", "").strip()
    if configured_model:
        return configured_model

    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=3)
        response.raise_for_status()
        models = response.json().get("models", [])
    except requests.RequestException:
        return DEFAULT_OLLAMA_MODEL

    model_names = [
        model.get("name")
        for model in models
        if isinstance(model, dict) and isinstance(model.get("name"), str)
    ]
    for model_name in model_names:
        if model_name == DEFAULT_OLLAMA_MODEL or model_name.startswith(f"{DEFAULT_OLLAMA_MODEL}:"):
            return model_name
    return model_names[0] if model_names else DEFAULT_OLLAMA_MODEL


def sanitize_topic_folder_name(topic_label_or_key):
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", str(topic_label_or_key).strip().lower()).strip("_")
    return cleaned or "python_project"


def get_topic_output_folder(topic_title_or_key, round_num=1):
    """Creates/resolves a folder named after the topic right inside the bot's folder."""
    base_name = sanitize_topic_folder_name(topic_title_or_key)
    folder_name = base_name if round_num == 1 else f"{base_name}_v{round_num}"
    full_path = os.path.join(BOT_BASE_DIR, folder_name)
    os.makedirs(full_path, exist_ok=True)
    return full_path


def clamp_speed(speed_val):
    """Clamps numeric speed between 0.001 and 0.015."""
    if isinstance(speed_val, str):
        legacy = {"fast": 0.005, "medium": 0.01, "slow": 0.015}
        if speed_val.strip().lower() in legacy:
            return legacy[speed_val.strip().lower()]
    try:
        val = float(speed_val)
    except (TypeError, ValueError):
        val = 0.015
    return max(MIN_SPEED, min(MAX_SPEED, round(val, 4)))


def check_abort():
    if STOP_FLAG:
        raise InterruptedError("EMERGENCY STOP TRIGGERED BY USER.")


def pace_sleep(speed=0.015, total_seconds=None):
    s = clamp_speed(speed)
    delay = total_seconds if total_seconds is not None else s
    elapsed = 0.0
    chunk = 0.15
    while elapsed < delay:
        check_abort()
        step = min(chunk, delay - elapsed)
        time.sleep(step)
        elapsed += step


def focus_window_by_keyword(keyword):
    check_abort()
    if not HAS_WIN32:
        return False

    matched_hwnd = None

    def _enum_cb(hwnd, _):
        nonlocal matched_hwnd
        if matched_hwnd is None and win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd) or ""
            if keyword.lower() in title.lower():
                matched_hwnd = hwnd

    win32gui.EnumWindows(_enum_cb, None)
    if matched_hwnd:
        try:
            win32gui.ShowWindow(matched_hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(matched_hwnd)
            return True
        except Exception:
            return False
    return False


def is_vscode_foreground():
    """Return whether VS Code owns the foreground window (Windows only)."""
    if not HAS_WIN32:
        return False
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        return "visual studio code" in title.lower()
    except Exception:
        return False


def is_vscode_editor_target():
    """Require VS Code foreground and the mouse over the editor text area."""
    if not HAS_WIN32 or not is_vscode_foreground():
        return False
    try:
        hwnd = win32gui.GetForegroundWindow()
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        x, y = pyautogui.position()
        width, height = right - left, bottom - top
        # Exclude the title/menu bars, activity/sidebar, and lower panel/status area.
        return (left + int(width * 0.28) <= x <= right - 8 and
                top + int(height * 0.12) <= y <= top + int(height * 0.68))
    except Exception:
        return False


def wait_for_vscode(deadline_ts=None):
    """Pause until VS Code is foreground and the pointer is over its editor area."""
    while not is_vscode_editor_target():
        check_abort()
        if deadline_ts is not None and time.time() >= deadline_ts:
            return False
        time.sleep(0.2)
    return True


def focus_vscode_editor(deadline_ts=None):
    """Focus the editor pane of the foreground VS Code window before any typing."""
    if not focus_window_by_keyword("Visual Studio Code"):
        return False
    check_abort()
    try:
        hwnd = win32gui.GetForegroundWindow()
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        # Target the central editor pane, away from the sidebar and bottom panel.
        x = left + int(width * 0.62)
        y = top + int(height * 0.40)
        pyautogui.moveTo(x, y, duration=0.12)
        pyautogui.click()
        time.sleep(0.15)
        if deadline_ts is not None and time.time() >= deadline_ts:
            return False
        return is_vscode_editor_target()
    except Exception:
        return False


def repair_python_syntax(file_name, code_content, syntax_error):
    """Ask the configured AI source for a syntax-only correction and validate it."""
    endpoint = os.getenv("CLEMOH_AI_ENDPOINT", "").strip()
    model = (
        os.getenv("CLEMOH_AI_MODEL", "").strip()
        if endpoint
        else resolve_ollama_model()
    )
    api_key = os.getenv("CLEMOH_AI_API_KEY", "").strip()
    prompt = (
        f"Fix the Python syntax error in {file_name}: {syntax_error}. "
        "Return only the complete corrected Python source code, without markdown fences. "
        "Preserve intended behavior and make the smallest necessary changes.\n\n"
        f"SOURCE:\n{code_content}"
    )
    try:
        if endpoint:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            response = requests.post(
                endpoint,
                headers=headers,
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
                timeout=60,
            )
            response.raise_for_status()
            repaired = response.json()["choices"][0]["message"]["content"]
        else:
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=60,
            )
            response.raise_for_status()
            repaired = response.json().get("response", "")
        repaired = repaired.strip()
        if repaired.startswith("```"):
            repaired = re.sub(r"^```(?:python)?\s*|\s*```$", "", repaired, flags=re.IGNORECASE)
        compile(repaired, file_name, "exec")
        return repaired
    except Exception:
        return None


def subtle_mouse_activity():
    """Moves the mouse gently within the active window so desktop I/O remains continuously active."""
    check_abort()
    screen_w, screen_h = pyautogui.size()
    x, y = pyautogui.position()
    dx = random.randint(-40, 40)
    dy = random.randint(-25, 25)
    target_x = max(140, min(screen_w - 140, x + dx))
    target_y = max(140, min(screen_h - 140, y + dy))
    pyautogui.moveTo(target_x, target_y, duration=0.16)


def switch_to_vscode(speed=0.015, folder_to_open=None):
    check_abort()
    if folder_to_open:
        os.makedirs(folder_to_open, exist_ok=True)
        subprocess.Popen(["code", os.path.abspath(folder_to_open)], shell=True)
        pace_sleep(speed, total_seconds=2.5)
        focus_window_by_keyword("Visual Studio Code")
        return f"Opened VS Code workspace folder '{folder_to_open}'."

    if not focus_window_by_keyword("Visual Studio Code"):
        subprocess.Popen(["code"], shell=True)
        pace_sleep(speed, total_seconds=2.8)
    else:
        pace_sleep(speed, total_seconds=0.7)
    return "Switched active window to VS Code."


def open_and_focus_excel(excel_path=None, speed=0.015):
    check_abort()
    if excel_path:
        abs_path = os.path.abspath(excel_path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        os.startfile(abs_path)
        pace_sleep(speed, total_seconds=2.8)
    elif not focus_window_by_keyword("Excel"):
        subprocess.Popen(["start", "excel"], shell=True)
        pace_sleep(speed, total_seconds=2.8)

    focus_window_by_keyword("Excel")
    pace_sleep(speed, total_seconds=0.7)
    return f"Opened and focused Excel ({excel_path or 'blank/active window'})."


def switch_between_vscode_and_excel(target_app, excel_path=None, speed=0.015):
    target = target_app.strip().lower()
    if target == "vscode":
        return switch_to_vscode(speed=speed)
    if target == "excel":
        return open_and_focus_excel(excel_path=excel_path, speed=speed)
    raise ValueError(f"Unknown app target '{target_app}'. Use 'vscode' or 'excel'.")


def open_vscode_and_write_code(folder_name, file_name, code_content, speed=0.015):
    check_abort()
    os.makedirs(folder_name, exist_ok=True)
    file_path = os.path.abspath(os.path.join(folder_name, file_name))

    subprocess.Popen(["code", file_path], shell=True)
    pace_sleep(speed, total_seconds=2.8)

    if not focus_vscode_editor():
        raise RuntimeError("Could not focus the VS Code editor; refusing to paste elsewhere.")
    check_abort()
    pyperclip.copy(code_content)
    pyautogui.hotkey("ctrl", "v")
    pace_sleep(speed, total_seconds=0.5)
    pyautogui.hotkey("ctrl", "s")
    pace_sleep(speed)
    return f"Opened VS Code, wrote {file_name}, and saved."


def human_type_code_in_vscode(
    folder_name,
    file_name,
    code_content,
    speed=0.015,
    deadline_ts=None,
    on_line_progress=None,
):
    """
    Types code slowly, waiting whenever VS Code is not the foreground application.
    """
    check_abort()
    s = clamp_speed(speed)
    if file_name.lower().endswith(".py"):
        try:
            compile(code_content, file_name, "exec")
        except SyntaxError as exc:
            fixed_code = repair_python_syntax(file_name, code_content, exc)
            if fixed_code is None:
                raise ValueError(
                    f"Could not repair invalid Python in {file_name}: {exc.msg} at line {exc.lineno}."
                ) from exc
            code_content = fixed_code
            if on_line_progress:
                on_line_progress(f"Detected a Python syntax error in {file_name}; AI corrected it before typing.")
    # Deliberately slow cadence; speed remains accepted for API compatibility.
    char_min = 0.28
    char_max = 0.55
    word_pause_min = 0.55
    word_pause_max = 0.95
    line_pause = 0.65

    file_path = os.path.abspath(os.path.join(folder_name, file_name))
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("")

    subprocess.Popen(["code", file_path], shell=True)
    pace_sleep(s, total_seconds=2.2)
    if not focus_window_by_keyword("Visual Studio Code"):
        raise RuntimeError("Could not find a VS Code window; refusing to type into another application.")
    if on_line_progress:
        on_line_progress(f"Focusing the VS Code editor for {file_name} before typing...")
    if not focus_vscode_editor(deadline_ts):
        return f"Could not focus the VS Code editor for '{file_name}'; no text was typed."

    lines = code_content.splitlines()

    for line_idx, line in enumerate(lines, start=1):
        check_abort()
        if not wait_for_vscode(deadline_ts):
            return f"Timer ended while waiting to type '{file_name}' at line {line_idx - 1}."
        if deadline_ts is not None and time.time() >= deadline_ts:
            if is_vscode_editor_target():
                pyautogui.hotkey("ctrl", "s")
            return f"Timer ended while coding '{file_name}' at line {line_idx - 1}."

        if not wait_for_vscode(deadline_ts):
            return f"Timer ended while waiting to edit '{file_name}'."
        pyautogui.press("home")
        pyautogui.hotkey("shift", "end")
        pyautogui.press("backspace")

        for ch in line:
            check_abort()
            if not wait_for_vscode(deadline_ts):
                return f"Timer ended while waiting mid-line in '{file_name}'."
            if deadline_ts is not None and time.time() >= deadline_ts:
                if is_vscode_editor_target():
                    pyautogui.hotkey("ctrl", "s")
                return f"Timer ended mid-line in '{file_name}'."
            pyautogui.write(ch, interval=0)
            if ch == " ":
                time.sleep(random.uniform(word_pause_min, word_pause_max))
            else:
                time.sleep(random.uniform(char_min, char_max))

        if not wait_for_vscode(deadline_ts):
            return f"Timer ended while waiting to continue '{file_name}'."
        pyautogui.press("enter")
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.15)
        expected_prefix = "\n".join(lines[:line_idx])
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                saved_prefix = f.read().replace("\r\n", "\n")
        except OSError:
            saved_prefix = None
        normalize_tail = lambda value: value.rstrip("\r\n").rstrip(" \t")
        if saved_prefix is not None and normalize_tail(saved_prefix) != normalize_tail(expected_prefix):
            if not wait_for_vscode(deadline_ts):
                return f"Detected a line error in '{file_name}', but could not reach VS Code to fix it."
            pyperclip.copy(expected_prefix + "\n")
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "v")
            pyautogui.hotkey("ctrl", "s")
            pyautogui.hotkey("ctrl", "end")
            time.sleep(0.2)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    repaired_prefix = f.read().replace("\r\n", "\n")
            except OSError:
                repaired_prefix = None
            if repaired_prefix is not None and normalize_tail(repaired_prefix) != normalize_tail(expected_prefix):
                return f"Line {line_idx} in '{file_name}' still differs after correction; check VS Code and save state."
            if on_line_progress:
                on_line_progress(f"Detected a skipped or altered line in {file_name}; corrected it immediately at line {line_idx}.")
        elif on_line_progress and line_idx % 12 == 0:
            on_line_progress(f"Typed and checked {line_idx}/{len(lines)} lines in {file_name} (speed={s})...")

        time.sleep(line_pause)

    if wait_for_vscode(deadline_ts):
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.5)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                saved_code = f.read().replace("\r\n", "\n")
        except OSError:
            saved_code = None
        expected_code = code_content.replace("\r\n", "\n").rstrip("\n")
        if saved_code is not None and saved_code.rstrip("\n") != expected_code:
            if not wait_for_vscode(deadline_ts):
                return f"Detected a mismatch in '{file_name}', but could not reach the editor to repair it."
            pyperclip.copy(code_content)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "v")
            pyautogui.hotkey("ctrl", "s")
            time.sleep(0.5)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    repaired_saved_code = f.read().replace("\r\n", "\n").rstrip("\n")
            except OSError:
                repaired_saved_code = None
            if on_line_progress:
                on_line_progress(f"Detected missing or altered text in {file_name}; restored the complete verified source.")
            if repaired_saved_code is not None and repaired_saved_code != expected_code:
                return f"Text mismatch remained after repair in '{file_name}'; check the VS Code editor and save state."
    pace_sleep(s, total_seconds=0.35)
    return f"Completed '{file_name}' ({len(lines)} lines saved at speed={s})."


def execute_terminal_command(command, speed=0.015):
    check_abort()
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    pace_sleep(speed, total_seconds=0.5)
    return result.stdout if result.returncode == 0 else result.stderr
