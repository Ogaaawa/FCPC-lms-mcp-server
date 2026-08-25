"""Setup wizard for the Moodle MCP server.

Enter your Moodle username and password, press one button, and it fetches a
web service token, checks it works and writes it to .env. There is no need to
open developer tools or hunt for a token by hand.

Run with:
    python setup_gui.py
    (or double-click setup.command on macOS, setup.bat on Windows)
"""
import queue
import threading
import tkinter as tk
from tkinter import ttk

import moodle_auth
from moodle_auth import MoodleAuthError

MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "llama3", "qwen2.5"]


class SetupApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.queue: queue.Queue = queue.Queue()
        self.busy = False

        root.title("Moodle MCP Setup")
        root.resizable(False, False)

        outer = ttk.Frame(root, padding=20)
        outer.grid(sticky="nsew")

        ttk.Label(
            outer, text="Moodle Assistant Setup", font=("", 16, "bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            outer,
            text="Use the same username and password you use for Moodle.\n"
                 "Your password stays on this computer and is not saved.",
            foreground="#555555",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 14))

        saved = moodle_auth.read_env()

        def placeholder(value, prefix="your_"):
            """Treat the .env template values (your_xxx) as empty."""
            return "" if not value or value.startswith(prefix) else value

        # --- Moodle account ---
        box = ttk.LabelFrame(outer, text=" Moodle ", padding=12)
        box.grid(row=2, column=0, columnspan=2, sticky="ew")
        box.columnconfigure(1, weight=1)

        self.url = tk.StringVar(
            value=placeholder(saved.get("MOODLE_URL")) or moodle_auth.DEFAULT_URL
        )
        self.username = tk.StringVar()
        self.password = tk.StringVar()

        self._row(box, 0, "Site address", self.url)
        self._row(box, 1, "Username", self.username)
        pw = self._row(box, 2, "Password", self.password, show="*")

        self.show_pw = tk.BooleanVar(value=False)

        def toggle_pw():
            pw.configure(show="" if self.show_pw.get() else "*")

        ttk.Checkbutton(
            box, text="Show password", variable=self.show_pw, command=toggle_pw
        ).grid(row=3, column=1, sticky="w", pady=(6, 0))

        # --- optional AI settings ---
        ai = ttk.LabelFrame(outer, text=" AI (optional) ", padding=12)
        ai.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ai.columnconfigure(1, weight=1)

        self.api_key = tk.StringVar(value=placeholder(saved.get("OPENAI_API_KEY")))
        self.model = tk.StringVar(value=placeholder(saved.get("LLM_MODEL")) or "gpt-4o")

        self._row(ai, 0, "OpenAI API key", self.api_key, show="*")
        ttk.Label(ai, text="Model").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Combobox(ai, textvariable=self.model, values=MODELS, width=28).grid(
            row=1, column=1, sticky="ew", pady=4
        )
        ttk.Label(
            ai,
            text="Only needed for client.py. Leave blank to skip.",
            foreground="#555555",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # --- Claude connector ---
        con = ttk.LabelFrame(outer, text=" Connector URL for Claude ", padding=12)
        con.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        con.columnconfigure(1, weight=1)

        self.server_base = tk.StringVar(value=placeholder(saved.get("CONNECTOR_BASE_URL")))
        self.connector = tk.StringVar()

        ttk.Label(con, text="Server address").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(con, textvariable=self.server_base, width=34).grid(
            row=0, column=1, sticky="ew", pady=4
        )
        ttk.Label(
            con,
            text="The address shown by start-server.command,\n"
                 "for example https://xxxx.trycloudflare.com",
            foreground="#555555",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(con, text="URL to register").grid(row=2, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(con, textvariable=self.connector, width=34, state="readonly").grid(
            row=2, column=1, sticky="ew", pady=4
        )
        ttk.Button(con, text="Copy", command=self.copy_connector).grid(
            row=3, column=1, sticky="e", pady=(4, 0)
        )
        ttk.Label(
            con,
            text="Every student registers this same URL.\nClaude handles signing in.",
            foreground="#555555",
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # --- buttons ---
        buttons = ttk.Frame(outer)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        self.run_button = ttk.Button(buttons, text="Connect and set up", command=self.on_setup)
        self.run_button.pack(side="left")
        self.test_button = ttk.Button(
            buttons, text="Test saved settings", command=self.on_test
        )
        self.test_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Close", command=root.destroy).pack(side="right")

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        # --- output ---
        self.status = tk.Text(outer, height=9, width=64, wrap="word", relief="solid", borderwidth=1)
        self.status.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.status.configure(state="disabled", background="#fafafa")
        self.status.tag_configure("ok", foreground="#12762e")
        self.status.tag_configure("ng", foreground="#c0261e")
        self.status.tag_configure("muted", foreground="#666666")

        self._log('Enter your username and password, then press '
                  '"Connect and set up".', "muted")

        root.after(100, self._drain_queue)

    def _row(self, parent, row, label, var, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=var, width=34, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        return entry

    # --- screen updates -------------------------------------------------
    def _log(self, text, tag=None, clear=False):
        self.status.configure(state="normal")
        if clear:
            self.status.delete("1.0", "end")
        self.status.insert("end", text + "\n", tag or ())
        self.status.see("end")
        self.status.configure(state="disabled")

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.run_button.configure(state=state)
        self.test_button.configure(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _drain_queue(self):
        """Move messages from the worker thread onto the screen."""
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._log(*payload)
            elif kind == "connector":
                self.connector.set(payload)
            elif kind == "done":
                self._set_busy(False)
        self.root.after(100, self._drain_queue)

    def _post(self, text, tag=None, clear=False):
        self.queue.put(("log", (text, tag, clear)))

    # --- actions --------------------------------------------------------
    def on_setup(self):
        if self.busy:
            return
        self._set_busy(True)
        self._log("", clear=True)
        threading.Thread(target=self._setup_worker, daemon=True).start()

    def _setup_worker(self):
        try:
            url = moodle_auth.normalize_url(self.url.get())
            self._post(f"1. Connecting to {url} ...")

            token = moodle_auth.fetch_token(url, self.username.get(), self.password.get())
            self._post("2. Got a token.", "ok")

            info = moodle_auth.verify_token(url, token)
            self._post("3. Verified the token works.", "ok")
            self._post(f"   Site: {info.get('sitename')}")
            self._post(f"   Signed in as: {info.get('fullname')} ({info.get('username')})")

            values = {"MOODLE_URL": url, "MOODLE_TOKEN": token}
            api_key = self.api_key.get().strip()
            model = self.model.get().strip()
            if api_key:
                values["OPENAI_API_KEY"] = api_key
            if model:
                values["LLM_MODEL"] = model

            path = moodle_auth.update_env(values)
            self._post(f"4. Saved your settings to {path}", "ok")

            normalized_base = self._show_connector()
            if normalized_base:
                moodle_auth.update_env({"CONNECTOR_BASE_URL": normalized_base})

            self._post("")
            self._post("Setup complete. You can close this window.", "ok")
            if not api_key:
                self._post(
                    "Note: client.py needs an OpenAI API key. "
                    "Everything else works without one.",
                    "muted",
                )
        except MoodleAuthError as e:
            self._post("")
            self._post("Setup did not complete.", "ng")
            self._post(str(e), "ng")
        except Exception as e:  # show unexpected failures rather than hiding them
            self._post("")
            self._post(f"Unexpected error: {type(e).__name__}: {e}", "ng")
        finally:
            self.queue.put(("done", None))

    def copy_connector(self):
        """Copy the generated URL to the clipboard."""
        url = self.connector.get()
        if not url:
            self._log('Run "Connect and set up" first.', "muted")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self._log("Copied. Paste it into Claude's custom connector dialog.", "ok")

    def _show_connector(self):
        """Work out the URL to register in Claude and show it."""
        base = self.server_base.get().strip()
        if not base:
            self._post("")
            self._post("5. No server address given, so no URL was built.", "muted")
            self._post("   Enter the address from start-server.command and run again.", "muted")
            return None
        url = moodle_auth.connector_url(base)
        self.queue.put(("connector", url))
        self._post("")
        self._post("5. This is the URL to give your students:", "ok")
        self._post(f"   {url}")
        self._post("   They paste it into Claude's custom connector dialog.", "ok")
        return moodle_auth.normalize_url(base)

    def on_test(self):
        if self.busy:
            return
        self._set_busy(True)
        self._log("", clear=True)
        threading.Thread(target=self._test_worker, daemon=True).start()

    def _test_worker(self):
        try:
            saved = moodle_auth.read_env()
            url, token = saved.get("MOODLE_URL"), saved.get("MOODLE_TOKEN")
            if not url or not token or token.startswith("your_"):
                self._post("No saved settings yet. Run setup first.", "ng")
                return
            self._post(f"Connecting to {url} with the saved token ...")
            info = moodle_auth.verify_token(url, token)
            self._post("Connected. Your settings are valid.", "ok")
            self._post(f"   Site: {info.get('sitename')}")
            self._post(f"   Signed in as: {info.get('fullname')} ({info.get('username')})")
        except MoodleAuthError as e:
            self._post(str(e), "ng")
        except Exception as e:
            self._post(f"Unexpected error: {type(e).__name__}: {e}", "ng")
        finally:
            self.queue.put(("done", None))


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("aqua")  # native look on macOS
    except tk.TclError:
        pass
    SetupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
