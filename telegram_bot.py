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


def edit_message_text(token, chat_id, message_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:4096] if len(text) > 4096 else text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup)
    return telegram_request(token, "editMessageText", payload)


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


def send_result_and_menu(token, chat_id, text, message_id=None):
    if message_id is not None:
        edit_message_text(token, chat_id, message_id, text, main_menu_keyboard())
    else:
        send_message(token, chat_id, text, reply_markup=main_menu_keyboard())


def do_list(token, chat_id, message_id=None):
    out, err, code = run_libersuite(["client", "list"])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out), message_id)
    else:
        txt = "<pre>%s</pre>" % escape_html(out)
        if len(txt) > 4000:
            send_message(token, chat_id, txt[:4000])
            if message_id is not None:
                edit_message_text(token, chat_id, message_id, "Libersuite Panel1\n\nیکی از دکمه‌های زیر را انتخاب کنید:", main_menu_keyboard())
            else:
                send_message(token, chat_id, "منوی اصلی:", reply_markup=main_menu_keyboard())
        else:
            send_result_and_menu(token, chat_id, txt, message_id)


def do_add_finish(token, chat_id, data, message_id=None):
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    traffic_raw = (data.get("traffic") or "0").strip()
    expires_raw = (data.get("expires") or "0").strip()
    lib_args = ["client", "add", username, password]
    try:
        t = int(traffic_raw) if traffic_raw else 0
        if t > 0:
            lib_args += ["--traffic-limit", str(t)]
    except ValueError:
        pass
    try:
        e = int(expires_raw) if expires_raw else 0
        if e > 0:
            lib_args += ["--expires-in", str(e)]
    except ValueError:
        pass
    out, err, code = run_libersuite(lib_args)
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out), message_id)
    else:
        send_result_and_menu(token, chat_id, "✅ کاربر '%s' اضافه شد." % escape_html(username), message_id)


def do_remove_finish(token, chat_id, username, message_id=None):
    out, err, code = run_libersuite(["client", "remove", username])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out), message_id)
    else:
        send_result_and_menu(token, chat_id, "✅ کاربر '%s' حذف شد." % escape_html(username), message_id)


def do_enable_finish(token, chat_id, username, message_id=None):
    out, err, code = run_libersuite(["client", "enable", username])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out), message_id)
    else:
        send_result_and_menu(token, chat_id, "✅ کاربر '%s' فعال شد." % escape_html(username), message_id)


def do_disable_finish(token, chat_id, username, message_id=None):
    out, err, code = run_libersuite(["client", "disable", username])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out), message_id)
    else:
        send_result_and_menu(token, chat_id, "✅ کاربر '%s' غیرفعال شد." % escape_html(username), message_id)


def do_export_finish(token, chat_id, username, server_ip=None, message_id=None):
    lib_args = ["client", "export", username]
    if server_ip:
        lib_args.append(server_ip)
    out, err, code = run_libersuite(lib_args)
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out), message_id)
    else:
        for block in (out or "").split("\n\n"):
            block = block.strip()
            if block and len(block) <= 4000:
                send_message(token, chat_id, "<pre>%s</pre>" % escape_html(block))
            elif block:
                for i in range(0, len(block), 4000):
                    send_message(token, chat_id, "<pre>%s</pre>" % escape_html(block[i:i+4000]))
        if message_id is not None:
            edit_message_text(token, chat_id, message_id, "Libersuite Panel\n\nیکی از دکمه‌های زیر را انتخاب کنید:", main_menu_keyboard())
        else:
            send_message(token, chat_id, "منوی اصلی:", reply_markup=main_menu_keyboard())


def do_restart(token, chat_id, message_id=None):
    out, err, code = run_libersuite(["restart"])
    if code != 0:
        send_result_and_menu(token, chat_id, "خطا:\n<code>%s</code>" % escape_html(err or out), message_id)
    else:
        send_result_and_menu(token, chat_id, "✅ پنل ریستارت شد.", message_id)


def do_status(token, chat_id, message_id=None):
    out, err, code = run_libersuite(["client", "list"])
    if code != 0:
        send_result_and_menu(token, chat_id, "وضعیت: خطا در اجرای libersuite", message_id)
    else:
        send_result_and_menu(token, chat_id, "پنل در حال اجرا.\n<pre>%s</pre>" % escape_html((out or "No clients")[:2000]), message_id)


def handle_callback(token, admin_id, chat_id, callback_query_id, data, message_id):
    answer_callback(token, callback_query_id)
    if data == "cancel":
        if chat_id in user_states:
            del user_states[chat_id]
        edit_message_text(token, chat_id, message_id, "انصراف داده شد.", main_menu_keyboard())
        return
    if data == "list":
        do_list(token, chat_id, message_id)
        return
    if data == "add":
        user_states[chat_id] = {"action": "add", "step": 1, "data": {}, "message_id": message_id}
        edit_message_text(token, chat_id, message_id, "مرحله 1/4\nنام کاربری را وارد کنید:", cancel_keyboard())
        return
    if data == "remove":
        user_states[chat_id] = {"action": "remove", "step": 1, "data": {}, "message_id": message_id}
        edit_message_text(token, chat_id, message_id, "نام کاربری را وارد کنید:", cancel_keyboard())
        return
    if data == "enable":
        user_states[chat_id] = {"action": "enable", "step": 1, "data": {}, "message_id": message_id}
        edit_message_text(token, chat_id, message_id, "نام کاربری را وارد کنید:", cancel_keyboard())
        return
    if data == "disable":
        user_states[chat_id] = {"action": "disable", "step": 1, "data": {}, "message_id": message_id}
        edit_message_text(token, chat_id, message_id, "نام کاربری را وارد کنید:", cancel_keyboard())
        return
    if data == "export":
        user_states[chat_id] = {"action": "export", "step": 1, "data": {}, "message_id": message_id}
        edit_message_text(token, chat_id, message_id, "نام کاربری را وارد کنید:", cancel_keyboard())
        return
    if data == "restart":
        do_restart(token, chat_id, message_id)
        return
    if data == "status":
        do_status(token, chat_id, message_id)
        return


def handle_text_with_state(token, admin_id, chat_id, text):
    text = (text or "").strip()
    state = user_states.get(chat_id)
    if not state:
        return False
    action = state["action"]
    step = state["step"]
    data = state["data"]
    msg_id = state.get("message_id")

    if action == "add":
        if step == 1:
            state["data"]["username"] = text
            state["step"] = 2
            edit_message_text(token, chat_id, msg_id, "مرحله 2/4\nرمز عبور را وارد کنید:", cancel_keyboard())
            return True
        if step == 2:
            state["data"]["password"] = text
            state["step"] = 3
            edit_message_text(token, chat_id, msg_id, "مرحله 3/4\nترافیک به گیگابایت (0 = نامحدود):", cancel_keyboard())
            return True
        if step == 3:
            state["data"]["traffic"] = text
            state["step"] = 4
            edit_message_text(token, chat_id, msg_id, "مرحله 4/4\nاعتبار به روز (0 = بدون انقضا):", cancel_keyboard())
            return True
        if step == 4:
            state["data"]["expires"] = text
            del user_states[chat_id]
            do_add_finish(token, chat_id, state["data"], msg_id)
            return True

    if action == "remove" and step == 1:
        del user_states[chat_id]
        do_remove_finish(token, chat_id, text, msg_id)
        return True
    if action == "enable" and step == 1:
        del user_states[chat_id]
        do_enable_finish(token, chat_id, text, msg_id)
        return True
    if action == "disable" and step == 1:
        del user_states[chat_id]
        do_disable_finish(token, chat_id, text, msg_id)
        return True
    if action == "export":
        if step == 1:
            state["data"]["username"] = text
            state["step"] = 2
            edit_message_text(token, chat_id, msg_id, "آدرس سرور (IP) را وارد کنید یا برای تشخیص خودکار «خودکار» بفرستید:", cancel_keyboard())
            return True
        if step == 2:
            server_ip = None if text in ("خودکار", "auto", "") else text
            del user_states[chat_id]
            do_export_finish(token, chat_id, state["data"]["username"], server_ip, msg_id)
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
            message_id = None

            if upd.get("callback_query"):
                cq = upd["callback_query"]
                from_id = cq.get("from", {}).get("id")
                chat_id = cq.get("message", {}).get("chat", {}).get("id")
                callback_query_id = cq.get("id")
                callback_data = cq.get("data")
                message_id = cq.get("message", {}).get("message_id")
            else:
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                chat_id = msg.get("chat", {}).get("id")
                from_id = msg.get("from", {}).get("id")
                text = msg.get("text") or ""
                message_id = None

            if from_id != admin_id:
                if chat_id:
                    send_message(token, chat_id, "دسترسی مجاز نیست. فقط ادمین.")
                if callback_query_id:
                    answer_callback(token, callback_query_id, "دسترسی مجاز نیست")
                continue

            try:
                if callback_data is not None:
                    handle_callback(token, admin_id, chat_id, callback_query_id, callback_data, message_id)
                else:
                    handle_message(token, admin_id, chat_id, text)
            except Exception as e:
                sys.stderr.write("handle error: %s\n" % e)
                sys.stderr.flush()
                if chat_id:
                    send_message(token, chat_id, "خطا: %s" % escape_html(str(e)), reply_markup=main_menu_keyboard())


if __name__ == "__main__":
    main()
