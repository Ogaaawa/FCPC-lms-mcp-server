"""Moodle MCP サーバのセットアップウィザード（GUI）。

ユーザー名とパスワードを入力してボタンを押すだけで、
トークン取得 -> .env 書き込み -> 接続確認 まで自動で行う。
開発者ツールを開いてトークンを探す必要はない。

起動:
    python setup_gui.py
    （macOS なら「セットアップ.command」をダブルクリック）
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

        root.title("Moodle MCP セットアップ")
        root.resizable(False, False)

        outer = ttk.Frame(root, padding=20)
        outer.grid(sticky="nsew")

        ttk.Label(
            outer,
            text="Moodle アシスタント セットアップ",
            font=("", 16, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            outer,
            text="Moodle にログインするときと同じユーザー名・パスワードを入力してください。\n"
                 "パスワードはこのパソコンの中だけで使われ、保存はされません。",
            foreground="#555555",
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 14))

        saved = moodle_auth.read_env()

        def placeholder(value, prefix="your_"):
            """.env のひな形の値（your_xxx）は未設定として扱う。"""
            return "" if not value or value.startswith(prefix) else value

        # --- Moodle の情報 ---
        box = ttk.LabelFrame(outer, text=" Moodle ", padding=12)
        box.grid(row=2, column=0, columnspan=2, sticky="ew")
        box.columnconfigure(1, weight=1)

        self.url = tk.StringVar(value=placeholder(saved.get("MOODLE_URL")) or moodle_auth.DEFAULT_URL)
        self.username = tk.StringVar()
        self.password = tk.StringVar()

        self._row(box, 0, "サイト URL", self.url)
        self._row(box, 1, "ユーザー名", self.username)
        pw = self._row(box, 2, "パスワード", self.password, show="●")

        self.show_pw = tk.BooleanVar(value=False)

        def toggle_pw():
            pw.configure(show="" if self.show_pw.get() else "●")

        ttk.Checkbutton(box, text="パスワードを表示", variable=self.show_pw, command=toggle_pw).grid(
            row=3, column=1, sticky="w", pady=(6, 0)
        )

        # --- AI の設定（任意） ---
        ai = ttk.LabelFrame(outer, text=" AI（質問に答えさせる場合のみ・省略可） ", padding=12)
        ai.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ai.columnconfigure(1, weight=1)

        self.api_key = tk.StringVar(value=placeholder(saved.get("OPENAI_API_KEY")))
        self.model = tk.StringVar(value=placeholder(saved.get("LLM_MODEL")) or "gpt-4o")

        self._row(ai, 0, "OpenAI API キー", self.api_key, show="●")
        ttk.Label(ai, text="モデル").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Combobox(ai, textvariable=self.model, values=MODELS, width=28).grid(
            row=1, column=1, sticky="ew", pady=4
        )

        # --- Claude コネクタ ---
        con = ttk.LabelFrame(outer, text=" Claude に登録する URL ", padding=12)
        con.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        con.columnconfigure(1, weight=1)

        self.server_base = tk.StringVar(value=placeholder(saved.get("CONNECTOR_BASE_URL")))
        self.connector = tk.StringVar()

        ttk.Label(con, text="サーバーのアドレス").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(con, textvariable=self.server_base, width=34).grid(
            row=0, column=1, sticky="ew", pady=4
        )
        ttk.Label(
            con,
            text="先生から知らされたアドレスを入れてください（例: https://xxxx.trycloudflare.com）",
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(con, text="あなた専用の URL").grid(row=2, column=0, sticky="w", padx=(0, 10))
        entry = ttk.Entry(con, textvariable=self.connector, width=34, state="readonly")
        entry.grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(con, text="コピー", command=self.copy_connector).grid(
            row=3, column=1, sticky="e", pady=(4, 0)
        )
        ttk.Label(
            con,
            text="この URL はパスワードと同じです。他の人に渡さないでください。",
            foreground="#c0261e",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # --- ボタン ---
        buttons = ttk.Frame(outer)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        self.run_button = ttk.Button(buttons, text="接続してセットアップ", command=self.on_setup)
        self.run_button.pack(side="left")
        self.test_button = ttk.Button(buttons, text="保存済み設定で接続テスト", command=self.on_test)
        self.test_button.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="閉じる", command=root.destroy).pack(side="right")

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        # --- 結果表示 ---
        self.status = tk.Text(outer, height=9, width=64, wrap="word", relief="solid", borderwidth=1)
        self.status.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.status.configure(state="disabled", background="#fafafa")
        self.status.tag_configure("ok", foreground="#12762e")
        self.status.tag_configure("ng", foreground="#c0261e")
        self.status.tag_configure("muted", foreground="#666666")

        self._log("ユーザー名とパスワードを入力して「接続してセットアップ」を押してください。", "muted")

        root.after(100, self._drain_queue)

    def _row(self, parent, row, label, var, show=None):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 10))
        entry = ttk.Entry(parent, textvariable=var, width=34, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        return entry

    # --- 画面更新 ---------------------------------------------------------
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
        """ワーカースレッドからのメッセージを画面に反映する。"""
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

    # --- 処理本体 ---------------------------------------------------------
    def on_setup(self):
        if self.busy:
            return
        self._set_busy(True)
        self._log("", clear=True)
        threading.Thread(target=self._setup_worker, daemon=True).start()

    def _setup_worker(self):
        try:
            url = moodle_auth.normalize_url(self.url.get())
            self._post(f"1. {url} に接続しています...")

            token = moodle_auth.fetch_token(url, self.username.get(), self.password.get())
            self._post("2. トークンを取得しました。", "ok")

            info = moodle_auth.verify_token(url, token)
            self._post("3. トークンが有効か確認しました。", "ok")
            self._post(f"   サイト: {info.get('sitename')}")
            self._post(f"   ログイン中: {info.get('fullname')} ({info.get('username')})")

            values = {"MOODLE_URL": url, "MOODLE_TOKEN": token}
            api_key = self.api_key.get().strip()
            model = self.model.get().strip()
            if api_key:
                values["OPENAI_API_KEY"] = api_key
            if model:
                values["LLM_MODEL"] = model

            path = moodle_auth.update_env(values)
            self._post(f"4. 設定を保存しました: {path}", "ok")

            normalized_base = self._show_connector(token)
            if normalized_base:
                moodle_auth.update_env({"CONNECTOR_BASE_URL": normalized_base})

            self._post("")
            self._post("セットアップ完了です。この画面は閉じて構いません。", "ok")
            if not api_key:
                self._post(
                    "※ AI に質問する機能（client.py）を使うには OpenAI API キーが必要です。",
                    "muted",
                )
        except MoodleAuthError as e:
            self._post("")
            self._post("セットアップできませんでした。", "ng")
            self._post(str(e), "ng")
        except Exception as e:  # 想定外の失敗も画面に出す
            self._post("")
            self._post(f"予期しないエラー: {type(e).__name__}: {e}", "ng")
        finally:
            self.queue.put(("done", None))


    def copy_connector(self):
        """生成された URL をクリップボードにコピーする。"""
        url = self.connector.get()
        if not url:
            self._log("先に「接続してセットアップ」を実行してください。", "muted")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self._log("URL をコピーしました。Claude のコネクタ追加画面に貼り付けてください。", "ok")

    def _show_connector(self, token):
        """Claude に登録する URL を組み立てて表示する。"""
        base = self.server_base.get().strip()
        if not base:
            self._post("")
            self._post("5. サーバーのアドレスが未入力のため URL を作れませんでした。", "muted")
            self._post("   先生から知らされたアドレスを入れて、もう一度実行してください。", "muted")
            return None
        url = moodle_auth.connector_url(base, token)
        self.queue.put(("connector", url))
        self._post("")
        self._post("5. あなた専用の URL を作りました。", "ok")
        self._post(f"   {url}")
        self._post("   Claude の「カスタムコネクタを追加」にこの URL を貼り付けてください。", "ok")
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
                self._post("保存された設定がありません。先にセットアップを行ってください。", "ng")
                return
            self._post(f"{url} に保存済みトークンで接続しています...")
            info = moodle_auth.verify_token(url, token)
            self._post("接続できました。設定は有効です。", "ok")
            self._post(f"   サイト: {info.get('sitename')}")
            self._post(f"   ログイン中: {info.get('fullname')} ({info.get('username')})")
        except MoodleAuthError as e:
            self._post(str(e), "ng")
        except Exception as e:
            self._post(f"予期しないエラー: {type(e).__name__}: {e}", "ng")
        finally:
            self.queue.put(("done", None))


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("aqua")  # macOS のネイティブ見た目
    except tk.TclError:
        pass
    SetupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
