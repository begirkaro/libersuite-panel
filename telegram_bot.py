#!/usr/bin/env python3
"""
Libersuite Telegram Bot - Management panel via Telegram.
Only responds to the numeric admin ID configured in config.env.
Uses only Python standard library (no pip install).
"""
import os
import re
import sys
import json
import subprocess
import urllib.request
import urllib.error
import urllib.parse

# Config next to script so it works under systemd when HOME is unset
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONF_FILE = os.path.join(SCRIPT_DIR, "config.env")
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 30


def load_config():
    """Load TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_ID from config.env."""
    if not os.path.isfile(CONF_FILE):
        sys.stderr.write("Config not found: %s\n" % CONF_FILE)
        sys.exit(1)
    env = {}
    with open(CONF_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                env[k.strip()] = v
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    admin_id = env.get("TELEGRAM_ADMIN_ID", "").strip()
    if not token or not admin_id:
        sys.stderr.write("TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_ID must be set in %s\n" % CONF_FILE)
        sys.exit(1)
    try:
        admin_id = int(admin_id)
    except ValueError:
        sys.stderr.write("TELEGRAM_ADMIN_ID must be a numeric ID\n")
        sys.exit(1)
    return token, admin_id


def telegram_request(token, method, data=None):
    url = TELEGRAM_API.format(token=token, method=method)
    if data is None:
        data = {}
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = ""
        sys.stderr.write("Telegram API error %s: %s\n" % (e.code, err_body))
        return None
    except Exception as e:
        sys.stderr.write("Request error: %s\n" % e)
        return None


def send_message(token, chat_id, text, parse_mode="HTML"):
    return telegram_request(token, "sendMessage", {
        "chat_id": chat_id,
        "text": text[:4096] if len(text) > 4096 else text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    })


def run_libersuite(args):
    """Run libersuite CLI and return (stdout, stderr, returncode)."""
    cmd = ["/usr/local/bin/libersuite"] + args
    env = os.environ.copy()
    # libersuite expects $HOME/libersuite/config.env; script is in that dir, so HOME = parent of script dir
    env["HOME"] = os.path.dirname(SCRIPT_DIR)
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            timeout=60,
            env=env,
            cwd=SCRIPT_DIR,
        )
        out = (p.stdout or b"").decode("utf-8", errors="replace").strip()
        err = (p.stderr or b"").decode("utf-8", errors="replace").strip()
        return out, err, p.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except FileNotFoundError:
        return "", "libersuite command not found (is /usr/local/bin/libersuite installed?)", -1
    except Exception as e:
        return "", str(e), -1


def escape_html(s):
    if not s:
        return ""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def handle_command(token, admin_id, chat_id, text):
    text = (text or "").strip()
    if not text.startswith("/"):
        return
    parts = re.split(r"\s+", text, maxsplit=1)
    cmd = parts[0].lower()
    rest = (parts[1].strip() if len(parts) > 1 else "")

    if cmd == "/start":
        send_message(token, chat_id,
            "Libersuite Panel\n\n"
            "دستورات:\n"
            "/list — لیست کاربران\n"
            "/add <user> <pass> [ترافیک_گیگ] [اعتبار_روز]\n"
            "/remove <user>\n"
            "/enable <user>\n"
            "/disable <user>\n"
            "/export <user> [ip]\n"
            "/restart — ریستارت پنل\n"
            "/status — وضعیت سرویس"
        )
        return

    if cmd == "/list":
        out, err, code = run_libersuite(["client", "list"])
        if code != 0:
            send_message(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
        else:
            send_message(token, chat_id, "<pre>%s</pre>" % escape_html(out))
        return

    if cmd == "/add":
        args = re.split(r"\s+", rest, maxsplit=3)
        if len(args) < 2:
            send_message(token, chat_id, "استفاده: /add &lt;username&gt; &lt;password&gt; [traffic_gb] [expires_days]")
            return
        username, password = args[0], args[1]
        traffic = args[2] if len(args) > 2 else ""
        expires = args[3] if len(args) > 3 else ""
        lib_args = ["client", "add", username, password]
        if traffic:
            lib_args += ["--traffic-limit", traffic]
        if expires:
            lib_args += ["--expires-in", expires]
        out, err, code = run_libersuite(lib_args)
        if code != 0:
            send_message(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
        else:
            send_message(token, chat_id, "کاربر '%s' اضافه شد." % escape_html(username))
        return

    if cmd == "/remove":
        if not rest:
            send_message(token, chat_id, "استفاده: /remove &lt;username&gt;")
            return
        username = rest.split()[0]
        out, err, code = run_libersuite(["client", "remove", username])
        if code != 0:
            send_message(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
        else:
            send_message(token, chat_id, "کاربر '%s' حذف شد." % escape_html(username))
        return

    if cmd == "/enable":
        if not rest:
            send_message(token, chat_id, "استفاده: /enable &lt;username&gt;")
            return
        username = rest.split()[0]
        out, err, code = run_libersuite(["client", "enable", username])
        if code != 0:
            send_message(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
        else:
            send_message(token, chat_id, "کاربر '%s' فعال شد." % escape_html(username))
        return

    if cmd == "/disable":
        if not rest:
            send_message(token, chat_id, "استفاده: /disable &lt;username&gt;")
            return
        username = rest.split()[0]
        out, err, code = run_libersuite(["client", "disable", username])
        if code != 0:
            send_message(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
        else:
            send_message(token, chat_id, "کاربر '%s' غیرفعال شد." % escape_html(username))
        return

    if cmd == "/export":
        args = rest.split()
        if not args:
            send_message(token, chat_id, "استفاده: /export &lt;username&gt; [server_ip]")
            return
        username = args[0]
        lib_args = ["client", "export", username]
        if len(args) > 1:
            lib_args.append(args[1])
        out, err, code = run_libersuite(lib_args)
        if code != 0:
            send_message(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
        else:
            for block in (out or "").split("\n\n"):
                block = block.strip()
                if block and len(block) <= 4000:
                    send_message(token, chat_id, "<pre>%s</pre>" % escape_html(block))
                elif block:
                    for i in range(0, len(block), 4000):
                        send_message(token, chat_id, "<pre>%s</pre>" % escape_html(block[i:i+4000]))
        return

    if cmd == "/restart":
        out, err, code = run_libersuite(["restart"])
        if code != 0:
            send_message(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
        else:
            send_message(token, chat_id, "پنل ریستارت شد.")
        return

    if cmd == "/status":
        out, err, code = run_libersuite(["client", "list"])
        if code != 0:
            send_message(token, chat_id, "وضعیت: خطا در اجرای libersuite")
        else:
            send_message(token, chat_id, "پنل در حال اجرا.\n<pre>%s</pre>" % escape_html((out or "No clients")[:2000]))
        return

    send_message(token, chat_id, "دستور نامعتبر. /start برای راهنما.")


def main():
    token, admin_id = load_config()
    sys.stderr.write("Libersuite bot started (admin_id=%s). Waiting for messages...\n" % admin_id)
    sys.stderr.flush()
    offset = None
    while True:
        url = TELEGRAM_API.format(token=token, method="getUpdates")
        params = {"timeout": POLL_TIMEOUT}
        if offset is not None:
            params["offset"] = offset
        q = urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen("%s?%s" % (url, q), timeout=POLL_TIMEOUT + 10) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            sys.stderr.write("Poll error: %s\n" % e)
            sys.stderr.flush()
            continue
        if not data.get("ok"):
            sys.stderr.write("getUpdates not ok: %s\n" % (json.dumps(data)[:500] if isinstance(data, dict) else str(data)))
            sys.stderr.flush()
            continue
        for upd in data.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat_id = msg.get("chat", {}).get("id")
            from_id = msg.get("from", {}).get("id")
            if from_id != admin_id:
                send_message(token, chat_id, "دسترسی مجاز نیست. فقط ادمین.")
                continue
            text = msg.get("text") or ""
            try:
                handle_command(token, admin_id, chat_id, text)
            except Exception as e:
                sys.stderr.write("handle_command error: %s\n" % e)
                sys.stderr.flush()
                send_message(token, chat_id, "خطا: %s" % escape_html(str(e)))


if __name__ == "__main__":
    main()
