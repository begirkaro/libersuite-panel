#!/usr/bin/env python3
"""
Libersuite Telegram Bot - Admin-only management panel.
Only responds to messages from TELEGRAM_ADMIN_ID.
Uses Telegram Bot API with long polling (no extra dependencies).
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Config from env (set by systemd from config.env)
BASE_DIR = os.environ.get("LIBERSUITE_BASE", os.path.expanduser("~/libersuite"))
CONF_FILE = os.path.join(BASE_DIR, "config.env")
LIBERSUITE_BIN = "/usr/local/bin/libersuite"


def load_config():
    """Load TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_ID from config.env."""
    config = {}
    if not os.path.isfile(CONF_FILE):
        return config
    with open(CONF_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                config[key] = value
    return config


def telegram_request(token, method, data=None):
    """Send request to Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    if data:
        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
            return {"ok": False, "description": body}
        except Exception:
            return {"ok": False, "description": str(e)}
    except Exception as e:
        return {"ok": False, "description": str(e)}


def send_message(token, chat_id, text, parse_mode="HTML"):
    """Send a message to chat_id. Truncate if too long for Telegram (4096)."""
    if len(text) > 4000:
        text = text[:3990] + "\n\n... (truncated)"
    return telegram_request(
        token,
        "sendMessage",
        {"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
    )


def run_libersuite(args, timeout=60):
    """Run libersuite CLI with env from config. Returns (stdout, stderr, returncode)."""
    env = os.environ.copy()
    env["HOME"] = os.path.expanduser("~")
    if os.path.isfile(CONF_FILE):
        with open(CONF_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    env[key] = value
    try:
        proc = subprocess.run(
            [LIBERSUITE_BIN] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=BASE_DIR,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        return out, err, proc.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except FileNotFoundError:
        return "", f"Command not found: {LIBERSUITE_BIN}", -1
    except Exception as e:
        return "", str(e), -1


def cmd_start(_token, _chat_id, _args):
    return """Libersuite Panel Bot

دستورات (فقط ادمین):
/help — راهنما
/add <user> <pass> [traffic_gb] [expires_days] — افزودن کاربر
/list — لیست کاربران
/remove <user> — حذف کاربر
/enable <user> — فعال‌سازی
/disable <user> — غیرفعال‌سازی
/export <user> [server_ip] — لینک اتصال
/restart — ریستارت سرویس‌ها
/status — وضعیت سرویس‌ها"""


def cmd_help(_token, _chat_id, _args):
    return cmd_start(_token, _chat_id, _args)


def cmd_add(token, chat_id, args):
    if len(args) < 2:
        return "استفاده: /add <username> <password> [traffic_gb] [expires_days]\nمثال: /add user1 pass123 10 30"
    username, password = args[0], args[1]
    traffic = args[2] if len(args) > 2 else ""
    expires = args[3] if len(args) > 3 else ""
    cmd = ["client", "add", username, password]
    if traffic:
        cmd.extend(["--traffic-limit", traffic])
    if expires:
        cmd.extend(["--expires-in", expires])
    out, err, code = run_libersuite(cmd)
    if code != 0:
        return f"خطا:\n{err or out}"
    return f"✅ کاربر '{username}' اضافه شد.\n{out}"


def cmd_list(_token, _chat_id, _args):
    out, err, code = run_libersuite(["client", "list"])
    if code != 0:
        return f"خطا:\n{err or out}"
    return out if out else "لیست خالی است."


def cmd_remove(_token, _chat_id, args):
    if not args:
        return "استفاده: /remove <username>"
    username = args[0]
    out, err, code = run_libersuite(["client", "remove", username])
    if code != 0:
        return f"خطا:\n{err or out}"
    return f"✅ کاربر '{username}' حذف شد."


def cmd_enable(_token, _chat_id, args):
    if not args:
        return "استفاده: /enable <username>"
    username = args[0]
    out, err, code = run_libersuite(["client", "enable", username])
    if code != 0:
        return f"خطا:\n{err or out}"
    return f"✅ کاربر '{username}' فعال شد."


def cmd_disable(_token, _chat_id, args):
    if not args:
        return "استفاده: /disable <username>"
    username = args[0]
    out, err, code = run_libersuite(["client", "disable", username])
    if code != 0:
        return f"خطا:\n{err or out}"
    return f"✅ کاربر '{username}' غیرفعال شد."


def cmd_export(_token, _chat_id, args):
    if not args:
        return "استفاده: /export <username> [server_ip]"
    username = args[0]
    server_ip = args[1] if len(args) > 1 else None
    cmd = ["client", "export", username]
    if server_ip:
        cmd.append(server_ip)
    out, err, code = run_libersuite(cmd)
    if code != 0:
        return f"خطا:\n{err or out}"
    return out if out else "خروجی خالی"


def cmd_restart(_token, _chat_id, _args):
    # Use sudo; install script adds NOPASSWD for libersuite restart
    try:
        proc = subprocess.run(
            ["sudo", LIBERSUITE_BIN, "restart"],
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ.copy(),
            cwd=BASE_DIR,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return f"خطا:\n{err or out}"
        return "✅ سرویس‌ها ریستارت شدند."
    except Exception as e:
        return f"خطا: {e}"


def cmd_status(_token, _chat_id, _args):
    out, err, code = run_libersuite(["client", "list"])
    lines = []
    # Quick service check via systemctl if available
    for svc in ["libersuite", "dnstt", "slipstream"]:
        try:
            p = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True,
                text=True,
                timeout=5,
            )
            status = (p.stdout or "").strip() or "inactive"
            lines.append(f"{svc}: {status}")
        except Exception:
            lines.append(f"{svc}: ?")
    return "\n".join(lines) + "\n\n" + (out if out else "No clients.")


COMMANDS = {
    "start": cmd_start,
    "help": cmd_help,
    "add": cmd_add,
    "list": cmd_list,
    "remove": cmd_remove,
    "enable": cmd_enable,
    "disable": cmd_disable,
    "export": cmd_export,
    "restart": cmd_restart,
    "status": cmd_status,
}


def handle_update(token, admin_id, update):
    """Process one update. Only respond if message is from admin."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg.get("chat", {}).get("id")
    user_id = msg.get("from", {}).get("id")
    text = (msg.get("text") or "").strip()

    if str(user_id) != str(admin_id):
        # Optional: reply "Access denied" or stay silent
        send_message(token, chat_id, "⛔ فقط ادمین مجاز است.")
        return

    if not text:
        return

    # Parse /command or /command args
    parts = text.split()
    if not parts:
        return
    cmd_part = parts[0]
    if cmd_part.startswith("/"):
        cmd_part = cmd_part[1:].split("@")[0].lower()
    else:
        return

    args = parts[1:]
    handler = COMMANDS.get(cmd_part)
    if not handler:
        send_message(token, chat_id, f"دستور نامعتبر. /help")
        return

    try:
        reply = handler(token, chat_id, args)
        send_message(token, chat_id, reply)
    except Exception as e:
        send_message(token, chat_id, f"خطا: {e}")


def main():
    config = load_config()
    token = config.get("TELEGRAM_BOT_TOKEN", "").strip()
    admin_id = config.get("TELEGRAM_ADMIN_ID", "").strip()

    if not token or not admin_id:
        print("TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_ID missing in config.env", file=sys.stderr)
        sys.exit(1)

    # Export for run_libersuite env
    os.environ["LIBERSUITE_BASE"] = BASE_DIR

    offset = None
    while True:
        try:
            data = {"timeout": 30}
            if offset is not None:
                data["offset"] = offset
            result = telegram_request(token, "getUpdates", data)
            if not result.get("ok"):
                print(result.get("description", "getUpdates failed"), file=sys.stderr)
                time.sleep(5)
                continue
            for upd in result.get("result", []):
                offset = upd["update_id"] + 1
                handle_update(token, admin_id, upd)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(e, file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
