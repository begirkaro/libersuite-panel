#!/usr/bin/env python3
"""
Libersuite Telegram Bot - Management panel via Telegram (button-based, step by step).
Only responds to the numeric admin ID configured in config.env.
"""
import os
import re
import sys
import json
import subprocess
import urllib.request
import urllib.error
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# config.env may be next to script or in parent (e.g. /root/libersuite/config.env when script is in .../libersuite/libersuite/)
CONF_FILE = os.path.join(SCRIPT_DIR, "config.env")
if not os.path.isfile(CONF_FILE):
    parent_conf = os.path.join(os.path.dirname(SCRIPT_DIR), "config.env")
    if os.path.isfile(parent_conf):
        CONF_FILE = parent_conf
# Directory containing config (for running libersuite CLI)
LIBERSUITE_DIR = os.path.dirname(CONF_FILE)
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 30

# state: chat_id -> {"action": "add"|"remove"|..., "step": int, "data": {...}}
user_states = {}


def load_config():
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


def send_message(token, chat_id, text, parse_mode="HTML", reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text[:4096] if len(text) > 4096 else text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)
    return telegram_request(token, "sendMessage", payload)


def answer_callback(token, callback_query_id, text=None):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text[:200]
    return telegram_request(token, "answerCallbackQuery", payload)


def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📋 لیست کاربران", "callback_data": "list"}],
            [{"text": "➕ افزودن کاربر", "callback_data": "add"}],
            [{"text": "❌ حذف کاربر", "callback_data": "remove"}, {"text": "✅ فعال کردن", "callback_data": "enable"}],
            [{"text": "⛔ غیرفعال کردن", "callback_data": "disable"}, {"text": "📤 خروجی کاربر", "callback_data": "export"}],
            [{"text": "🔄 ریستارت پنل", "callback_data": "restart"}, {"text": "📊 وضعیت", "callback_data": "status"}],
        ]
    }


def cancel_keyboard():
    return {"inline_keyboard": [[{"text": "❌ انصراف", "callback_data": "cancel"}]]}


def run_libersuite(args):
    cmd = ["/usr/local/bin/libersuite"] + args
    env = os.environ.copy()
    env["HOME"] = os.path.dirname(LIBERSUITE_DIR)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=60, env=env, cwd=LIBERSUITE_DIR)
        out = (p.stdout or b"").decode("utf-8", errors="replace").strip()
        err = (p.stderr or b"").decode("utf-8", errors="replace").strip()
        return out, err, p.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except FileNotFoundError:
        return "", "libersuite command not found", -1
    except Exception as e:
        return "", str(e), -1


def escape_html(s):
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_result_and_menu(token, chat_id, text):
    send_message(token, chat_id, text, reply_markup=main_menu_keyboard())


def do_list(token, chat_id):
    out, err, code = run_libersuite(["client", "list"])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
    else:
        send_result_and_menu(token, chat_id, "<pre>%s</pre>" % escape_html(out))


def do_add_finish(token, chat_id, data):
    username = data.get("username", "")
    password = data.get("password", "")
    traffic = data.get("traffic", "0")
    expires = data.get("expires", "0")
    lib_args = ["client", "add", username, password]
    if traffic and traffic != "0":
        lib_args += ["--traffic-limit", traffic]
    if expires and expires != "0":
        lib_args += ["--expires-in", expires]
    out, err, code = run_libersuite(lib_args)
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
    else:
        send_result_and_menu(token, chat_id, "✅ کاربر '%s' اضافه شد." % escape_html(username))


def do_remove_finish(token, chat_id, username):
    out, err, code = run_libersuite(["client", "remove", username])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
    else:
        send_result_and_menu(token, chat_id, "✅ کاربر '%s' حذف شد." % escape_html(username))


def do_enable_finish(token, chat_id, username):
    out, err, code = run_libersuite(["client", "enable", username])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
    else:
        send_result_and_menu(token, chat_id, "✅ کاربر '%s' فعال شد." % escape_html(username))


def do_disable_finish(token, chat_id, username):
    out, err, code = run_libersuite(["client", "disable", username])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
    else:
        send_result_and_menu(token, chat_id, "✅ کاربر '%s' غیرفعال شد." % escape_html(username))


def do_export_finish(token, chat_id, username, server_ip=None):
    lib_args = ["client", "export", username]
    if server_ip:
        lib_args.append(server_ip)
    out, err, code = run_libersuite(lib_args)
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
    else:
        for block in (out or "").split("\n\n"):
            block = block.strip()
            if block and len(block) <= 4000:
                send_message(token, chat_id, "<pre>%s</pre>" % escape_html(block))
            elif block:
                for i in range(0, len(block), 4000):
                    send_message(token, chat_id, "<pre>%s</pre>" % escape_html(block[i:i+4000]))
        send_message(token, chat_id, "منوی اصلی:", reply_markup=main_menu_keyboard())


def do_restart(token, chat_id):
    out, err, code = run_libersuite(["restart"])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out))
    else:
        send_result_and_menu(token, chat_id, "✅ پنل ریستارت شد.")


def do_status(token, chat_id):
    out, err, code = run_libersuite(["client", "list"])
    if code != 0:
        send_result_and_menu(token, chat_id, "وضعیت: خطا در اجرای libersuite")
    else:
        send_result_and_menu(token, chat_id, "پنل در حال اجرا.\n<pre>%s</pre>" % escape_html((out or "No clients")[:2000]))


def handle_callback(token, admin_id, chat_id, callback_query_id, data):
    answer_callback(token, callback_query_id)
    if data == "cancel":
        if chat_id in user_states:
            del user_states[chat_id]
        send_message(token, chat_id, "انصراف داده شد.", reply_markup=main_menu_keyboard())
        return
    if data == "list":
        do_list(token, chat_id)
        return
    if data == "add":
        user_states[chat_id] = {"action": "add", "step": 1, "data": {}}
        send_message(token, chat_id, "مرحله ۱/۴\nنام کاربری را وارد کنید:", reply_markup=cancel_keyboard())
        return
    if data == "remove":
        user_states[chat_id] = {"action": "remove", "step": 1, "data": {}}
        send_message(token, chat_id, "نام کاربری را وارد کنید:", reply_markup=cancel_keyboard())
        return
    if data == "enable":
        user_states[chat_id] = {"action": "enable", "step": 1, "data": {}}
        send_message(token, chat_id, "نام کاربری را وارد کنید:", reply_markup=cancel_keyboard())
        return
    if data == "disable":
        user_states[chat_id] = {"action": "disable", "step": 1, "data": {}}
        send_message(token, chat_id, "نام کاربری را وارد کنید:", reply_markup=cancel_keyboard())
        return
    if data == "export":
        user_states[chat_id] = {"action": "export", "step": 1, "data": {}}
        send_message(token, chat_id, "نام کاربری را وارد کنید:", reply_markup=cancel_keyboard())
        return
    if data == "restart":
        do_restart(token, chat_id)
        return
    if data == "status":
        do_status(token, chat_id)
        return


def handle_text_with_state(token, admin_id, chat_id, text):
    text = (text or "").strip()
    state = user_states.get(chat_id)
    if not state:
        return False
    action = state["action"]
    step = state["step"]
    data = state["data"]

    if action == "add":
        if step == 1:
            state["data"]["username"] = text
            state["step"] = 2
            send_message(token, chat_id, "مرحله ۲/۴\nرمز عبور را وارد کنید:", reply_markup=cancel_keyboard())
            return True
        if step == 2:
            state["data"]["password"] = text
            state["step"] = 3
            send_message(token, chat_id, "مرحله ۳/۴\nترافیک به گیگابایت (۰ = نامحدود):", reply_markup=cancel_keyboard())
            return True
        if step == 3:
            state["data"]["traffic"] = text
            state["step"] = 4
            send_message(token, chat_id, "مرحله ۴/۴\nاعتبار به روز (۰ = بدون انقضا):", reply_markup=cancel_keyboard())
            return True
        if step == 4:
            state["data"]["expires"] = text
            del user_states[chat_id]
            do_add_finish(token, chat_id, state["data"])
            return True

    if action == "remove" and step == 1:
        del user_states[chat_id]
        do_remove_finish(token, chat_id, text)
        return True
    if action == "enable" and step == 1:
        del user_states[chat_id]
        do_enable_finish(token, chat_id, text)
        return True
    if action == "disable" and step == 1:
        del user_states[chat_id]
        do_disable_finish(token, chat_id, text)
        return True
    if action == "export":
        if step == 1:
            state["data"]["username"] = text
            state["step"] = 2
            send_message(token, chat_id, "آدرس سرور (IP) را وارد کنید یا برای تشخیص خودکار «خودکار» بفرستید:", reply_markup=cancel_keyboard())
            return True
        if step == 2:
            server_ip = None if text in ("خودکار", "auto", "") else text
            del user_states[chat_id]
            do_export_finish(token, chat_id, state["data"]["username"], server_ip)
            return True
    return False


def handle_message(token, admin_id, chat_id, text):
    if handle_text_with_state(token, admin_id, chat_id, text):
        return
    if (text or "").strip() == "/start" or not text:
        send_message(
            token, chat_id,
            "Libersuite Panel\n\nیکی از دکمه‌های زیر را انتخاب کنید:",
            reply_markup=main_menu_keyboard()
        )
        return
    send_message(token, chat_id, "از منو دکمه انتخاب کنید یا /start بزنید.", reply_markup=main_menu_keyboard())


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
            chat_id = None
            from_id = None
            text = None
            callback_query_id = None
            callback_data = None

            if upd.get("callback_query"):
                cq = upd["callback_query"]
                from_id = cq.get("from", {}).get("id")
                chat_id = cq.get("message", {}).get("chat", {}).get("id")
                callback_query_id = cq.get("id")
                callback_data = cq.get("data")
            else:
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                chat_id = msg.get("chat", {}).get("id")
                from_id = msg.get("from", {}).get("id")
                text = msg.get("text") or ""

            if from_id != admin_id:
                if chat_id:
                    send_message(token, chat_id, "دسترسی مجاز نیست. فقط ادمین.")
                if callback_query_id:
                    answer_callback(token, callback_query_id, "دسترسی مجاز نیست")
                continue

            try:
                if callback_data is not None:
                    handle_callback(token, admin_id, chat_id, callback_query_id, callback_data)
                else:
                    handle_message(token, admin_id, chat_id, text)
            except Exception as e:
                sys.stderr.write("handle error: %s\n" % e)
                sys.stderr.flush()
                if chat_id:
                    send_message(token, chat_id, "خطا: %s" % escape_html(str(e)), reply_markup=main_menu_keyboard())


if __name__ == "__main__":
    main()
