import json
import os
import re
import time
import requests
import tools_desktop
from project_blueprints import PROJECT_QUEUES, get_project_blueprint
from tools_excel import create_fees_register, run_analytics_cycle
from tools_desktop import (
    clamp_speed,
    pace_sleep,
    get_topic_output_folder,
    switch_to_vscode,
    open_vscode_and_write_code,
    human_type_code_in_vscode,
    repair_python_syntax,
    DEFAULT_OLLAMA_MODEL,
    resolve_ollama_model,
    execute_terminal_command,
    switch_between_vscode_and_excel,
)
from tools_vision import take_screenshot, click_template_image, click_by_description

OLLAMA_URL = "http://localhost:11434/api/generate"
AI_CHAT_ENDPOINT = os.getenv("CLEMOH_AI_ENDPOINT", "").strip()
AI_CHAT_MODEL = os.getenv("CLEMOH_AI_MODEL", "").strip()
AI_CHAT_API_KEY = os.getenv("CLEMOH_AI_API_KEY", "").strip()

ALLOWED_TOOLS = [
    "create_file",
    "create_excel",
    "vscode_write",
    "switch_app",
    "run_command",
    "take_screenshot",
    "click_ui",
    "chat",
]

RISKY_TOOLS = {"run_command", "click_ui"}

WORKFLOW_SYSTEM_PROMPT = """
You are CLEMOH AI, a Windows Desktop Automation Agent that plans multi-step workflows.
Break the user's request into an ordered list of steps.

Return ONLY valid JSON with this structure:
{
  "goal": "short summary of the workflow",
  "steps": [
    {
      "step_number": 1,
      "title": "short action title",
      "tool": "create_file | create_excel | vscode_write | switch_app | run_command | take_screenshot | click_ui | chat",
      "risky": true or false,
      "params": {}
    }
  ]
}
Use these exact parameter names:
- create_file: {"path": "relative/or/absolute/file path", "content": "complete file contents"}
- create_excel: {"filename": "output.xlsx"}
- vscode_write: {"folder": "folder path", "filename": "file name", "code": "complete file contents"}
- switch_app: {"target": "vscode"} or {"target": "excel"}
- run_command: {"command": "command to run"}
- take_screenshot: {"filename": "screen.png"}
- click_ui: {"target": "description"} or {"template_path": "image path"}
- chat: {"reply": "response to the user"}
"""


def _extract_json_object(text):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"Could not parse JSON plan from model output: {text}")
        return json.loads(match.group(0))


def _fallback_workflow(user_prompt):
    topic_folder = get_topic_output_folder(user_prompt, round_num=1)
    starter_code = (
        f"# Full system starter for: {user_prompt}\n"
        "def main():\n"
        f'    print("Running {user_prompt} system...")\n\n'
        'if __name__ == "__main__":\n'
        "    main()\n"
    )
    return {
        "goal": f"Build full system for '{user_prompt}' inside '{topic_folder}'",
        "steps": [
            {
                "step_number": 1,
                "title": f"Create folder & write app.py in {os.path.basename(topic_folder)}",
                "tool": "vscode_write",
                "risky": False,
                "params": {"folder": topic_folder, "filename": "app.py", "code": starter_code},
            }
        ],
    }


def _normalize_workflow(raw_plan, user_prompt):
    if not isinstance(raw_plan, dict) or not isinstance(raw_plan.get("steps"), list) or not raw_plan["steps"]:
        return _fallback_workflow(user_prompt)

    normalized_steps = []
    for idx, step in enumerate(raw_plan["steps"], start=1):
        if not isinstance(step, dict):
            continue
        tool = step.get("tool", "chat")
        if tool not in ALLOWED_TOOLS:
            tool = "chat"
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        if tool == "vscode_write":
            if not params.get("filename") and params.get("file_name"):
                params["filename"] = params["file_name"]
            if not params.get("code") and params.get("text"):
                params["code"] = params["text"]
        elif tool == "switch_app":
            if not params.get("target") and params.get("app_name"):
                params["target"] = params["app_name"]
            target = str(params.get("target", "")).strip().lower()
            if target in {"visual studio code", "vs code"}:
                params["target"] = "vscode"
        elif tool == "create_file" and not params.get("path") and params.get("filename"):
            params["path"] = os.path.join(params.get("folder", ""), params["filename"])
        if tool == "chat" and "reply" not in params:
            params["reply"] = step.get("title", "Completed step.")

        file_exists = False
        if tool == "create_file" and params.get("path"):
            file_exists = os.path.exists(params["path"])

        is_risky = bool(step.get("risky", False)) or (tool in RISKY_TOOLS) or (tool == "switch_app") or file_exists
        normalized_steps.append(
            {
                "step_number": idx,
                "title": step.get("title") or f"Step {idx}: {tool}",
                "tool": tool,
                "risky": is_risky,
                "params": params,
            }
        )

    if not normalized_steps:
        return _fallback_workflow(user_prompt)

    return {
        "goal": raw_plan.get("goal") or user_prompt,
        "steps": normalized_steps,
    }


def plan_workflow(user_prompt, on_progress=None):
    task_folder = os.path.join(
        tools_desktop.BOT_BASE_DIR,
        tools_desktop.sanitize_topic_folder_name(user_prompt),
    )
    model_name = resolve_ollama_model()
    payload = {
        "model": model_name,
        "prompt": (
            f"{WORKFLOW_SYSTEM_PROMPT}\n\n"
            f"Task output folder: {task_folder}\n"
            "Keep every created file in that folder. Do not invent paths elsewhere or create folders "
            "with create_file. Use vscode_write with the exact folder, filename, and complete code.\n\n"
            f"User Command: {user_prompt}"
        ),
        "stream": False,
        "format": "json",
    }
    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=180)
        res.raise_for_status()
        parsed = _extract_json_object(res.json().get("response", ""))
        return _normalize_workflow(parsed, user_prompt)
    except Exception as exc:
        if on_progress:
            on_progress(f"AI planning unavailable ({exc}); using the built-in starter workflow.")
        return _fallback_workflow(user_prompt)


def generate_project_files_with_ai(project, on_progress=None, deadline_ts=None):
    """Use a configured OpenAI-compatible AI source or local Ollama to deepen a blueprint."""
    tools_desktop.check_abort()
    files = project.get("files", [])
    context = "\n\n".join(
        f"--- {path} ---\n{content}" for path, content in files
    )
    prompt = (
        "Build a complete, coherent, runnable system for the project below. Improve the supplied starter "
        "files and add other necessary files. Include practical workflows, validation, safe database access, "
        "clear setup instructions, and an attractive responsive interface where applicable. Keep it suitable "
        "for a local student/demo system. Keep the implementation focused and concise. Return ONLY JSON shaped as "
        '{"files":[{"path":"relative/path","content":"full file text"}]}. '
        "Use at most 5 files, typically 2-4; preserve the project name and avoid secrets. "
        "Keep the complete response under 3500 tokens.\n\n"
        f"Project: {project.get('title')}\nSlug: {project.get('key')}\n"
        f"Starter files:\n{context}"
    )
    ollama_model = resolve_ollama_model() if not AI_CHAT_ENDPOINT else None
    source_name = AI_CHAT_MODEL or ollama_model or DEFAULT_OLLAMA_MODEL
    try:
        remaining = 180 if deadline_ts is None else deadline_ts - time.time()
        if remaining <= 0:
            return files
        request_timeout = max(1, min(180, remaining))
        if on_progress:
            on_progress(f"Gathering project requirements and implementation guidance from AI ({source_name})...")
        if AI_CHAT_ENDPOINT:
            headers = {"Content-Type": "application/json"}
            if AI_CHAT_API_KEY:
                headers["Authorization"] = f"Bearer {AI_CHAT_API_KEY}"
            response = requests.post(
                AI_CHAT_ENDPOINT,
                headers=headers,
                json={
                    "model": AI_CHAT_MODEL or DEFAULT_OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a senior software architect and implementation assistant. Return valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                },
                timeout=request_timeout,
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
        else:
            response_chunks = []
            with requests.post(
                OLLAMA_URL,
                json={
                    "model": ollama_model,
                    "prompt": prompt,
                    "stream": True,
                    "format": "json",
                    "options": {"num_predict": 4096},
                },
                timeout=(5, request_timeout),
                stream=True,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    tools_desktop.check_abort()
                    if deadline_ts is not None and time.time() >= deadline_ts:
                        if on_progress:
                            on_progress("AI generation reached the session time limit; using the built-in project blueprint.")
                        return files
                    if not line:
                        continue
                    chunk = json.loads(line)
                    response_chunks.append(chunk.get("response", ""))
                    if chunk.get("done"):
                        break
            answer = "".join(response_chunks)
        generated = _extract_json_object(answer).get("files", [])
        clean_files = []
        for item in generated[:5]:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).replace("\\", "/").strip(" /")
            content = item.get("content")
            if (not path or ":" in path or ".." in path.split("/")
                    or path.startswith("/") or not isinstance(content, str)):
                continue
            if path.endswith(".py"):
                try:
                    compile(content, path, "exec")
                except SyntaxError as exc:
                    content = repair_python_syntax(path, content, exc)
                    if content is None:
                        raise ValueError(f"AI output for {path} has an unrepairable syntax error: {exc}")
            clean_files.append((path, content))
        if not clean_files:
            raise ValueError("The AI source returned no usable project files.")
        if on_progress:
            on_progress(f"AI-assisted project research/build used {source_name}; prepared {len(clean_files)} file(s).")
        return clean_files
    except Exception as exc:
        if on_progress:
            source = AI_CHAT_ENDPOINT or OLLAMA_URL
            on_progress(f"AI project generation unavailable from {source} ({exc}); using the built-in project blueprint.")
        return files


def create_file_safely(path, content):
    tools_desktop.check_abort()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote file '{os.path.abspath(path)}' ({len(content)} chars)."


def execute_step(step, speed=0.015):
    tools_desktop.check_abort()
    s = clamp_speed(speed)
    tool = step.get("tool")
    params = step.get("params", {})

    if tool == "create_file":
        return create_file_safely(params.get("path", "output.txt"), params.get("content", ""))
    if tool == "create_excel":
        return create_fees_register(params.get("filename", "Fees_Register.xlsx"))
    if tool == "vscode_write":
        return open_vscode_and_write_code(
            params.get("folder", get_topic_output_folder("clemoh_project")),
            params.get("filename", "script.py"),
            params.get("code", "# Generated by CLEMOH AI"),
            speed=s,
        )
    if tool == "switch_app":
        return switch_between_vscode_and_excel(
            params.get("target", "excel"),
            excel_path=params.get("excel_path"),
            speed=s,
        )
    if tool == "run_command":
        return execute_terminal_command(params.get("command", "echo Ready"), speed=s)
    if tool == "take_screenshot":
        path, _ = take_screenshot(params.get("filename", "screen.png"))
        return f"Screenshot saved to {path}"
    if tool == "click_ui":
        template_path = params.get("template_path")
        if template_path:
            return click_template_image(template_path)
        return click_by_description(params.get("target", ""))
    return params.get("reply", "Done.")


def execute_workflow(
    workflow,
    approval_callback=None,
    approve_all_steps=True,
    speed=0.015,
    on_step_start=None,
    on_step_done=None,
):
    results = []
    for step in workflow.get("steps", []):
        tools_desktop.check_abort()

        if on_step_start:
            on_step_start(step)

        needs_approval = approve_all_steps or step.get("risky", False)
        if needs_approval and approval_callback is not None:
            approved = approval_callback(step)
            if not approved:
                msg = f"Skipped step {step['step_number']} ({step['title']}) — not approved."
                if on_step_done:
                    on_step_done(step, msg, skipped=True)
                results.append({"step": step["step_number"], "status": "skipped", "output": msg})
                continue

        output = execute_step(step, speed=speed)
        if on_step_done:
            on_step_done(step, output, skipped=False)
        results.append({"step": step["step_number"], "status": "completed", "output": output})

    return results


def run_timed_project_suite_coding(
    start_project_key="restaurant_management_system",
    speed=0.015,
    duration_minutes=600,
    auto_advance_next_topic=True,
    on_progress=None,
):
    """
    Opens VS Code, creates a folder named after the chosen topic inside the bot's folder,
    codes all files of that full system into that folder, then checks and moves to the next topic.
    """
    s = clamp_speed(speed)
    capped_minutes = max(0.2, min(float(duration_minutes), 600.0))
    deadline_ts = time.time() + (capped_minutes * 60.0)

    start_idx = next((i for i, p in enumerate(PROJECT_QUEUES) if p["key"] == start_project_key), 0)
    queue_to_run = PROJECT_QUEUES[start_idx:] if auto_advance_next_topic else [get_project_blueprint(start_project_key)]

    completed_projects = []
    files_coded = 0
    round_num = 1

    while time.time() < deadline_ts:
        tools_desktop.check_abort()
        for proj_idx, proj in enumerate(queue_to_run):
            if time.time() >= deadline_ts:
                break

            topic_folder = get_topic_output_folder(proj["key"], round_num=round_num)
            folder_basename = os.path.basename(topic_folder)

            if on_progress:
                on_progress(
                    f"=== TOPIC [{proj_idx + 1}/{len(queue_to_run)}]: {proj['title']} -> Folder inside bot dir: '{folder_basename}' (speed={s}) ==="
                )

            project_files = generate_project_files_with_ai(
                proj, on_progress=on_progress, deadline_ts=deadline_ts
            )

            switch_to_vscode(speed=s, folder_to_open=topic_folder)

            for rel_file, code in project_files:
                if time.time() >= deadline_ts:
                    break
                if on_progress:
                    on_progress(f"Creating & typing '{folder_basename}/{rel_file}' in VS Code (speed={s})...")

                status = human_type_code_in_vscode(
                    folder_name=topic_folder,
                    file_name=rel_file,
                    code_content=code,
                    speed=s,
                    deadline_ts=deadline_ts,
                    on_line_progress=on_progress,
                )
                files_coded += 1
                if on_progress:
                    on_progress(status)

            if time.time() < deadline_ts:
                completed_projects.append(f"{proj['title']} ({folder_basename})")
                next_proj = queue_to_run[proj_idx + 1] if (proj_idx + 1) < len(queue_to_run) else None
                if on_progress:
                    if next_proj:
                        on_progress(
                            f"Completed '{proj['title']}' in '{folder_basename}'. Checking next topic -> '{next_proj['title']}'..."
                        )
                    else:
                        on_progress(f"Completed '{proj['title']}' in '{folder_basename}'.")

        if not auto_advance_next_topic:
            break
        queue_to_run = PROJECT_QUEUES
        round_num += 1

    return (
        f"Session finished ({capped_minutes} min, speed={s}). "
        f"Files coded: {files_coded}. Systems completed: {len(completed_projects)}."
    )


def run_endurance_analytics(
    analytics_key="sales_revenue_analytics",
    speed=0.015,
    duration_minutes=60,
    cycle_interval_sec=10.0,
    write_starter_code=True,
    switch_windows=True,
    on_progress=None,
):
    s = clamp_speed(speed)
    capped_minutes = max(0.1, min(float(duration_minutes), 600.0))
    end_time = time.time() + (capped_minutes * 60.0)
    cycle = 0
    excel_file = None

    if write_starter_code:
        tools_desktop.check_abort()
        starter_script = (
            "import openpyxl\n\n"
            "def summarize_workbook(path):\n"
            "    wb = openpyxl.load_workbook(path)\n"
            "    print('Sheets:', wb.sheetnames, 'Rows:', wb.active.max_row)\n"
        )
        open_vscode_and_write_code(
            get_topic_output_folder("clemoh_analytics"),
            "analytics_helper.py",
            starter_script,
            speed=s,
        )
        if on_progress:
            on_progress("Wrote analytics_helper.py in VS Code.")

    while time.time() < end_time:
        tools_desktop.check_abort()
        cycle += 1

        excel_file, msg = run_analytics_cycle(analytics_key, cycle_num=cycle, filename=excel_file)
        if on_progress:
            on_progress(msg)

        if cycle == 1 or switch_windows:
            switch_between_vscode_and_excel("excel", excel_path=excel_file, speed=s)
            if on_progress:
                on_progress(f"Switched to Excel showing '{excel_file}'.")

        if switch_windows and cycle % 3 == 0:
            switch_between_vscode_and_excel("vscode", speed=s)
            if on_progress:
                on_progress("Switched to VS Code to inspect script.")

        remaining = end_time - time.time()
        if remaining <= 0:
            break
        pace_sleep(speed=s, total_seconds=min(float(cycle_interval_sec) * s, remaining))

    return f"Completed {cycle} analytics cycle(s) over up to {capped_minutes} min in '{excel_file}'."


def plan_action(user_prompt):
    wf = plan_workflow(user_prompt)
    first = wf["steps"][0]
    return {"tool": first["tool"], "risky": first["risky"], "params": first["params"]}


def execute_plan(plan):
    return execute_step(plan)
