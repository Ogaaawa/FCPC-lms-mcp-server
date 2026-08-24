"""Gemini CLI にこの MCP サーバを登録する。

学生が手作業で ~/.gemini/settings.json を編集しなくて済むようにするための処理。
既存の設定は壊さずマージする。
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
GEMINI_DIR = os.path.join(os.path.expanduser("~"), ".gemini")
SETTINGS_PATH = os.path.join(GEMINI_DIR, "settings.json")
TRUSTED_PATH = os.path.join(GEMINI_DIR, "trustedFolders.json")
SERVER_NAME = "moodle"


class GeminiSetupError(Exception):
    """利用者にそのまま見せられる日本語メッセージを持つ例外。"""


def python_executable() -> str:
    """このプロジェクトの venv の python を優先して返す。"""
    for candidate in (
        os.path.join(ROOT, "venv", "bin", "python"),
        os.path.join(ROOT, "venv", "Scripts", "python.exe"),  # Windows
    ):
        if os.path.exists(candidate):
            return candidate
    return sys.executable


def gemini_path() -> str | None:
    """gemini 実行ファイルの絶対パス。Windows では gemini.cmd を解決する。"""
    return shutil.which("gemini")


def is_installed() -> bool:
    return gemini_path() is not None


def _load_json(path: str) -> dict:
    """壊れた JSON は上書きせず例外にする（学生の既存設定を守るため）。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        return json.loads(text) if text else {}
    except json.JSONDecodeError as e:
        raise GeminiSetupError(
            f"{path} が壊れているため書き換えられません。\n"
            f"内容を確認するか、ファイルを削除してからやり直してください。\n\n詳細: {e}"
        )


def _save_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        shutil.copyfile(path, path + ".bak")  # 念のため退避
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def register() -> list:
    """MCP サーバの登録とフォルダ信頼設定を行い、実施内容を返す。"""
    done = []

    settings = _load_json(SETTINGS_PATH)
    servers = settings.setdefault("mcpServers", {})
    entry = {
        "command": python_executable(),
        "args": [os.path.join(ROOT, "server.py")],
        "cwd": ROOT,
        "timeout": 60000,
    }
    if servers.get(SERVER_NAME) == entry:
        done.append("Gemini CLI には登録済みでした。")
    else:
        servers[SERVER_NAME] = entry
        _save_json(SETTINGS_PATH, settings)
        done.append(f"Gemini CLI に登録しました: {SETTINGS_PATH}")

    # 信頼されていないフォルダでは MCP サーバが無効化されるため
    trusted = _load_json(TRUSTED_PATH)
    if trusted.get(ROOT) == "TRUST_FOLDER":
        done.append("フォルダは信頼済みでした。")
    else:
        trusted[ROOT] = "TRUST_FOLDER"
        _save_json(TRUSTED_PATH, trusted)
        done.append("このフォルダを信頼済みに設定しました。")

    return done


def verify(timeout: int = 120) -> str:
    """`gemini mcp list` で接続状態を確認して、その行を返す。"""
    exe = gemini_path()
    if exe is None:
        raise GeminiSetupError(
            "Gemini CLI が見つかりません。\n"
            "先に次のコマンドでインストールしてください:\n"
            "    npm install -g @google/gemini-cli"
        )
    try:
        # Windows の gemini.cmd は名前だけでは起動できないので絶対パスで呼ぶ
        proc = subprocess.run(
            [exe, "mcp", "list"],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise GeminiSetupError("gemini mcp list が時間内に終わりませんでした。")

    output = (proc.stdout or "") + (proc.stderr or "")
    for line in output.splitlines():
        if SERVER_NAME in line:
            return line.strip()
    raise GeminiSetupError(f"登録を確認できませんでした。\n\n{output.strip()[:400]}")


if __name__ == "__main__":
    for line in register():
        print(line)
    print(verify())
