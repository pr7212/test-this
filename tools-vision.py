import os
import pyautogui


def take_screenshot(filename="screen.png"):
    abs_path = os.path.abspath(filename)
    parent = os.path.dirname(abs_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    img = pyautogui.screenshot()
    img.save(abs_path)
    return abs_path, img.size


def click_template_image(template_path, confidence=0.8):
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template image not found: {template_path}")
    loc = pyautogui.locateCenterOnScreen(template_path)
    if not loc:
        raise RuntimeError(f"Could not locate template '{template_path}' on screen.")
    pyautogui.click(loc.x, loc.y)
    return f"Clicked template '{template_path}' at ({loc.x}, {loc.y})."


def click_by_description(target_desc):
    w, h = pyautogui.size()
    cx, cy = int(w * 0.5), int(h * 0.5)
    pyautogui.click(cx, cy)
    return f"Clicked fallback target '{target_desc}' at ({cx}, {cy})."
