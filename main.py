import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk
import keyboard
import tools_desktop
from agent_core import (
    plan_workflow,
    execute_workflow,
    run_endurance_analytics,
    run_timed_project_suite_coding,
)
from project_blueprints import ALL_TOPICS
from tools_excel import ANALYTICS_CATALOG


class ClemohApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CLEMOH AI — Desktop Automation Agent")
        self.root.geometry("820x760")
        self.root.configure(bg="#121417")

        keyboard.add_hotkey("esc", self.emergency_stop)

        # Header
        tk.Label(
            root,
            text="CLEMOH AI",
            font=("Segoe UI", 20, "bold"),
            fg="#00E5FF",
            bg="#121417",
        ).pack(pady=(10, 0))
        tk.Label(
            root,
            text="AUTONOMOUS DESKTOP AUTOMATION AGENT",
            font=("Segoe UI", 9, "bold"),
            fg="#8A94A6",
            bg="#121417",
        ).pack()

        # Status Bar
        self.status_var = tk.StringVar(value="● SYSTEM READY | Press ESC anytime for Emergency Stop")
        self.status_label = tk.Label(
            root,
            textvariable=self.status_var,
            font=("Consolas", 10),
            fg="#00E676",
            bg="#1C2026",
            pady=6,
        )
        self.status_label.pack(fill="x", padx=20, pady=8)

        # Subsystems Grid
        grid_frame = tk.Frame(root, bg="#121417")
        grid_frame.pack(fill="x", padx=20)
        subsystems = [
            ("VS Code", "Ready"),
            ("Excel Engine", "Ready"),
            ("Project Menu", f"{len(ALL_TOPICS)} Topics"),
            ("Safety Gate", "Active"),
        ]
        for i, (name, state) in enumerate(subsystems):
            card = tk.Frame(grid_frame, bg="#1C2026", padx=10, pady=5)
            card.grid(row=0, column=i, padx=4, sticky="ew")
            grid_frame.columnconfigure(i, weight=1)
            tk.Label(card, text=name, font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#1C2026").pack()
            tk.Label(card, text=state, font=("Segoe UI", 8), fg="#00E5FF", bg="#1C2026").pack()

        # Command Input
        tk.Label(
            root,
            text="Command Centre:",
            font=("Segoe UI", 10, "bold"),
            fg="#E0E0E0",
            bg="#121417",
        ).pack(anchor="w", padx=20, pady=(8, 3))

        self.cmd_entry = tk.Entry(
            root,
            font=("Segoe UI", 11),
            bg="#1C2026",
            fg="#FFFFFF",
            insertbackground="white",
            relief="flat",
        )
        self.cmd_entry.pack(fill="x", padx=20, ipady=6)
        self.cmd_entry.insert(0, "Build Restaurant Management System in VS Code")
        self.cmd_entry.bind("<Return>", lambda e: self.run_task())

        # Approval Mode Checkbox
        self.approve_every_step_var = tk.BooleanVar(value=False)
        self.approval_mode_label_var = tk.StringVar()
        self._sync_approval_label()

        mode_frame = tk.Frame(root, bg="#121417")
        mode_frame.pack(fill="x", padx=20, pady=(6, 0))

        tk.Checkbutton(
            mode_frame,
            variable=self.approve_every_step_var,
            command=self._sync_approval_label,
            text="Approve every step",
            font=("Segoe UI", 9, "bold"),
            fg="#00E5FF",
            bg="#121417",
            activebackground="#121417",
            activeforeground="#00E5FF",
            selectcolor="#1C2026",
            bd=0,
            highlightthickness=0,
        ).pack(side="left")

        tk.Label(
            mode_frame,
            textvariable=self.approval_mode_label_var,
            font=("Segoe UI", 8, "italic"),
            fg="#9AA5B4",
            bg="#121417",
        ).pack(side="left", padx=(10, 0))

        # Manual Speed Input (<= 0.015) + Slider + Duration
        timing_frame = tk.Frame(root, bg="#1C2026", padx=10, pady=7)
        timing_frame.pack(fill="x", padx=20, pady=(7, 0))

        tk.Label(timing_frame, text="Speed (<=0.015):", font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#1C2026").pack(side="left")
        self.speed_var = tk.DoubleVar(value=0.015)
        self.manual_speed_entry = tk.Entry(
            timing_frame,
            width=8,
            font=("Consolas", 9, "bold"),
            bg="#121417",
            fg="#00E5FF",
            insertbackground="white",
        )
        self.manual_speed_entry.insert(0, "0.015")
        self.manual_speed_entry.pack(side="left", padx=(6, 4))

        def _on_slider_change(val):
            self.manual_speed_entry.delete(0, tk.END)
            self.manual_speed_entry.insert(0, f"{float(val):.4f}".rstrip("0").rstrip("."))

        def _on_manual_speed_commit(event=None):
            clamped = tools_desktop.clamp_speed(self.manual_speed_entry.get())
            self.speed_var.set(clamped)
            self.manual_speed_entry.delete(0, tk.END)
            self.manual_speed_entry.insert(0, f"{clamped:.4f}".rstrip("0").rstrip("."))

        self.manual_speed_entry.bind("<Return>", _on_manual_speed_commit)
        self.manual_speed_entry.bind("<FocusOut>", _on_manual_speed_commit)

        tk.Scale(
            timing_frame,
            from_=0.001,
            to=0.015,
            resolution=0.001,
            orient="horizontal",
            variable=self.speed_var,
            command=_on_slider_change,
            showvalue=False,
            length=135,
            bg="#1C2026",
            fg="#00E5FF",
            troughcolor="#121417",
            highlightthickness=0,
        ).pack(side="left", padx=4)

        tk.Label(timing_frame, text="Mins (600=10h):", font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#1C2026").pack(side="left", padx=(10, 0))
        self.duration_entry = tk.Entry(timing_frame, width=8, font=("Consolas", 9), bg="#121417", fg="#FFFFFF", insertbackground="white")
        self.duration_entry.insert(0, "600")
        self.duration_entry.pack(side="left", padx=4)

        # Row 1: Topic Selection Menu + Auto Next Topic toggle
        coding_frame = tk.Frame(root, bg="#1C2026", padx=10, pady=8)
        coding_frame.pack(fill="x", padx=20, pady=(6, 0))

        tk.Label(coding_frame, text="Select Topic:", font=("Segoe UI", 9, "bold"), fg="#00E5FF", bg="#1C2026").pack(side="left")

        self._label_to_key = {item["title"]: item["key"] for item in ALL_TOPICS}
        topic_titles = [item["title"] for item in ALL_TOPICS]
        self.topic_var = tk.StringVar(value=topic_titles[0])
        self.topic_combo = ttk.Combobox(
            coding_frame,
            textvariable=self.topic_var,
            values=topic_titles,
            width=36,
            state="readonly",
        )
        self.topic_combo.pack(side="left", padx=6)

        self.auto_next_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            coding_frame,
            variable=self.auto_next_var,
            text="Next topic after finish",
            font=("Segoe UI", 8, "bold"),
            fg="#E0E0E0",
            bg="#1C2026",
            activebackground="#1C2026",
            activeforeground="#00E5FF",
            selectcolor="#121417",
            bd=0,
            highlightthickness=0,
        ).pack(side="left", padx=4)

        tk.Button(
            coding_frame,
            text="⌨ Build Full System in VS Code",
            font=("Segoe UI", 9, "bold"),
            bg="#00E676",
            fg="#000000",
            relief="flat",
            padx=10,
            pady=3,
            command=self.run_project_suite_mode,
        ).pack(side="right")

        # Row 2: Excel Endurance Analytics Loop
        analytics_frame = tk.Frame(root, bg="#1C2026", padx=10, pady=7)
        analytics_frame.pack(fill="x", padx=20, pady=(6, 0))

        tk.Label(analytics_frame, text="Excel Analytics:", font=("Segoe UI", 9, "bold"), fg="#FFFFFF", bg="#1C2026").pack(side="left")
        self.analytics_keys = list(ANALYTICS_CATALOG.keys())
        self.analytics_var = tk.StringVar(value=self.analytics_keys[0])
        ttk.Combobox(analytics_frame, textvariable=self.analytics_var, values=self.analytics_keys, width=24, state="readonly").pack(side="left", padx=6)

        tk.Button(
            analytics_frame,
            text="📊 Run Excel Analytics Loop",
            font=("Segoe UI", 9, "bold"),
            bg="#7C4DFF",
            fg="#FFFFFF",
            relief="flat",
            padx=12,
            pady=3,
            command=self.run_analytics_mode,
        ).pack(side="right")

        # Action Buttons
        btn_frame = tk.Frame(root, bg="#121417")
        btn_frame.pack(fill="x", padx=20, pady=9)

        tk.Button(
            btn_frame,
            text="▶ EXECUTE TASK",
            font=("Segoe UI", 10, "bold"),
            bg="#00B8D4",
            fg="#000000",
            relief="flat",
            padx=14,
            pady=5,
            command=self.run_task,
        ).pack(side="left")

        tk.Button(
            btn_frame,
            text="? ASK WHAT TO BUILD",
            font=("Segoe UI", 9, "bold"),
            bg="#263238",
            fg="#00E5FF",
            relief="flat",
            padx=12,
            pady=5,
            command=self.ask_what_to_build,
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            btn_frame,
            text="■ EMERGENCY STOP (ESC)",
            font=("Segoe UI", 10, "bold"),
            bg="#FF1744",
            fg="#FFFFFF",
            relief="flat",
            padx=14,
            pady=5,
            command=self.emergency_stop,
        ).pack(side="right")

        # Activity & Plan Log
        self.log_box = scrolledtext.ScrolledText(
            root,
            height=11,
            font=("Consolas", 9),
            bg="#0D0F12",
            fg="#CFD8DC",
            relief="flat",
        )
        self.log_box.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        self.log(f"CLEMOH AI initialized with {len(ALL_TOPICS)} project topics. Standing by...")

    def _sync_approval_label(self):
        if self.approve_every_step_var.get():
            self.approval_mode_label_var.set("(Mode: Approve every step)")
        else:
            self.approval_mode_label_var.set("(Mode: Approve risky steps only)")

    def _get_speed(self):
        manual_val = tools_desktop.clamp_speed(self.manual_speed_entry.get())
        self.speed_var.set(manual_val)
        return manual_val

    def _get_duration_mins(self, default=600.0):
        try:
            mins = float(self.duration_entry.get().strip())
        except ValueError:
            mins = default
        return max(0.2, min(mins, 600.0))

    def log(self, message):
        def _append():
            self.log_box.insert(tk.END, f"> {message}\n")
            self.log_box.see(tk.END)

        if threading.current_thread() is threading.main_thread():
            _append()
        else:
            self.root.after(0, _append)

    def _set_status(self, text, color):
        def _update():
            self.status_var.set(text)
            self.status_label.config(fg=color)

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            self.root.after(0, _update)

    def emergency_stop(self):
        tools_desktop.STOP_FLAG = True
        self._set_status("■ EMERGENCY STOP ACTIVATED", "#FF1744")
        self.log("EMERGENCY STOP: Halting all mouse, keyboard, and process actions.")

    def _prepare_run(self):
        tools_desktop.STOP_FLAG = False

    def ask_what_to_build(self):
        user_idea = simpledialog.askstring(
            "CLEMOH AI — Ask What to Build",
            "What code project or workflow do you want CLEMOH AI to build?",
            parent=self.root,
        )
        if user_idea and user_idea.strip():
            self.cmd_entry.delete(0, tk.END)
            self.cmd_entry.insert(0, user_idea.strip())
            self.run_task()

    def run_task(self):
        prompt = self.cmd_entry.get().strip()
        if not prompt:
            self.ask_what_to_build()
            return
        self._prepare_run()
        approve_all = bool(self.approve_every_step_var.get())
        speed = self._get_speed()
        self._set_status("● PLANNING WORKFLOW...", "#FFD600")
        self.log(f"Command: {prompt} (speed={speed})")

        threading.Thread(target=self._worker, args=(prompt, approve_all, speed), daemon=True).start()

    def run_project_suite_mode(self):
        selected_title = self.topic_var.get()
        start_key = self._label_to_key.get(selected_title, selected_title)
        speed = self._get_speed()
        capped_mins = self._get_duration_mins(600.0)
        auto_next = bool(self.auto_next_var.get())

        self._prepare_run()
        self._set_status(f"● BUILDING '{selected_title}' (speed={speed})...", "#FFD600")
        self.log(
            f"Starting topic '{selected_title}' at manual speed={speed} "
            f"(auto_next={auto_next}, duration={capped_mins}m)."
        )

        def _suite_worker():
            try:
                summary = run_timed_project_suite_coding(
                    start_project_key=start_key,
                    speed=speed,
                    duration_minutes=capped_mins,
                    auto_advance_next_topic=auto_next,
                    on_progress=self.log,
                )
                self.log(summary)
                self._set_status("● SYSTEM BUILD COMPLETE — READY", "#00E676")
            except InterruptedError as ie:
                self.log(str(ie))
                self._set_status("■ EMERGENCY STOP ACTIVATED", "#FF1744")
            except Exception as exc:
                self.log(f"Error: {exc}")
                self._set_status("● ERROR ENCOUNTERED", "#FF1744")

        threading.Thread(target=_suite_worker, daemon=True).start()

    def run_analytics_mode(self):
        analytics_key = self.analytics_var.get()
        speed = self._get_speed()
        capped_mins = self._get_duration_mins(600.0)

        self._prepare_run()
        self._set_status(f"● RUNNING ANALYTICS (speed={speed}, {capped_mins}m)...", "#FFD600")
        self.log(f"Starting '{ANALYTICS_CATALOG.get(analytics_key, analytics_key)}' at speed={speed} for {capped_mins} min(s).")

        def _analytics_worker():
            try:
                summary = run_endurance_analytics(
                    analytics_key=analytics_key,
                    speed=speed,
                    duration_minutes=capped_mins,
                    cycle_interval_sec=10.0,
                    write_starter_code=True,
                    switch_windows=True,
                    on_progress=self.log,
                )
                self.log(summary)
                self._set_status("● ANALYTICS LOOP COMPLETE — SYSTEM READY", "#00E676")
            except InterruptedError as ie:
                self.log(str(ie))
                self._set_status("■ EMERGENCY STOP ACTIVATED", "#FF1744")
            except Exception as exc:
                self.log(f"Error: {exc}")
                self._set_status("● ERROR ENCOUNTERED", "#FF1744")

        threading.Thread(target=_analytics_worker, daemon=True).start()

    def _display_planned_steps(self, workflow):
        steps = workflow.get("steps", [])
        self.log(f"=== PLANNED WORKFLOW: {workflow.get('goal', 'Task')} ({len(steps)} step(s)) ===")
        for step in steps:
            risk_tag = "RISKY" if step.get("risky") else "SAFE"
            self.log(
                f"  {step['step_number']}. [{risk_tag}] {step['title']} "
                f"(tool={step['tool']}, params={step.get('params', {})})"
            )
        self.log("=== END OF PLAN ===")

    def _ask_step_approval_on_ui(self, step):
        if tools_desktop.STOP_FLAG:
            return False

        event = threading.Event()
        decision = {"approved": False}

        def _prompt():
            if tools_desktop.STOP_FLAG:
                decision["approved"] = False
                event.set()
                return

            risk_label = "RISKY" if step.get("risky") else "Safe"
            msg = (
                f"Step {step['step_number']}: {step['title']}\n"
                f"Risk Level: {risk_label} | Tool: {step['tool']}\n"
                f"Parameters: {step.get('params', {})}\n\n"
                "Approve and execute this step?"
            )
            decision["approved"] = messagebox.askyesno("CLEMOH AI — Step Approval", msg)
            event.set()

        self.root.after(0, _prompt)
        event.wait()
        return decision["approved"]

    def _worker(self, prompt, approve_all, speed):
        try:
            workflow = plan_workflow(prompt, on_progress=self.log)
            self._display_planned_steps(workflow)
            self._set_status("● EXECUTING WORKFLOW...", "#FFD600")

            execute_workflow(
                workflow,
                approval_callback=self._ask_step_approval_on_ui,
                approve_all_steps=approve_all,
                speed=speed,
                on_step_start=lambda s: self.log(f"[Step {s['step_number']}] Starting: {s['title']}..."),
                on_step_done=lambda s, out, skipped: self.log(f"[Step {s['step_number']}] {out}"),
            )

            self._set_status("● WORKFLOW COMPLETE — SYSTEM READY", "#00E676")
        except InterruptedError as ie:
            self.log(str(ie))
            self._set_status("■ EMERGENCY STOP ACTIVATED", "#FF1744")
        except Exception as exc:
            self.log(f"Error: {exc}")
            self._set_status("● ERROR ENCOUNTERED", "#FF1744")


if __name__ == "__main__":
    root = tk.Tk()
    app = ClemohApp(root)
    root.mainloop()
