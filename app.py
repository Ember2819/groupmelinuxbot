#!/usr/bin/env python3
"""
GroupMe Remote Command Bot for Le Potato (Ubuntu 22.04)
Runs as root — exposes shell execution to all group members via GroupMe.
"""

import subprocess
import socket
import datetime
import requests
from flask import Flask, request, jsonify

# ─────────────────────────────────────────────
#  CONFIGURATION  ← edit these two values
# ─────────────────────────────────────────────
BOT_ID   = "YOUR_BOT_ID_HERE"       # GroupMe Bot ID
GROUP_ID = "YOUR_GROUP_ID_HERE"     # Only used for the homing beacon on startup
# ─────────────────────────────────────────────

GROUPME_POST_URL = "https://api.groupme.com/v3/bots/post"
CMD_TIMEOUT      = 30   # seconds before a shell command is killed

app = Flask(__name__)


# ── Helpers ──────────────────────────────────

def send_message(text: str) -> None:
    """Post a message to the GroupMe group via the bot."""
    # GroupMe messages are capped at 1000 chars
    if len(text) > 950:
        text = text[:950] + "\n…(truncated)"
    payload = {"bot_id": BOT_ID, "text": text}
    try:
        requests.post(GROUPME_POST_URL, json=payload, timeout=10)
    except requests.RequestException as exc:
        app.logger.error("Failed to send GroupMe message: %s", exc)


def get_local_ip() -> str:
    """Return the primary local (LAN) IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "unknown"


def get_cpu_temp() -> str:
    """Read CPU temperature — tries vcgencmd first, then thermal_zone0."""
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()   # e.g. "temp=45.0'C"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            millideg = int(f.read().strip())
            return f"temp={millideg / 1000:.1f}'C"
    except Exception as exc:
        return f"Error reading temperature: {exc}"


def run_shell(command: str) -> str:
    """Execute an arbitrary shell command and return stdout+stderr."""
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT
        )
        output = proc.stdout.strip()
        errors = proc.stderr.strip()

        parts = []
        if output:
            parts.append(output)
        if errors:
            parts.append(f"[stderr]\n{errors}")
        if not parts:
            parts.append(f"(command exited with code {proc.returncode}, no output)")
        return "\n".join(parts)

    except subprocess.TimeoutExpired:
        return f"⏱ Command timed out after {CMD_TIMEOUT}s."
    except Exception as exc:
        return f"❌ Execution error: {exc}"


# ── Command dispatch ─────────────────────────

HELP_TEXT = """\
🤖 Le Potato Bot — available commands:
  !help          — show this message
  !temp          — current CPU temperature
  !run <cmd>     — execute a shell command and return output
"""

def handle_command(text: str) -> None:
    text = text.strip()

    if text == "!help":
        send_message(HELP_TEXT)

    elif text == "!temp":
        send_message(f"🌡 {get_cpu_temp()}")

    elif text.startswith("!run "):
        command = text[5:].strip()
        if not command:
            send_message("Usage: !run <command>")
            return
        send_message(f"$ {command}\n{run_shell(command)}")

    # Silently ignore messages that aren't bot commands


# ── Flask routes ─────────────────────────────

@app.route("/", methods=["POST"])
def groupme_webhook():
    """Receive incoming GroupMe messages."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "ignored", "reason": "no JSON"}), 200

    # Ignore messages sent by bots (including ourselves) to prevent loops
    if data.get("sender_type") == "bot":
        return jsonify({"status": "ignored", "reason": "bot message"}), 200

    text = data.get("text", "")
    if text.startswith("!"):
        handle_command(text)

    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "alive", "ip": get_local_ip()}), 200


# ── Startup homing beacon ────────────────────

def send_homing_beacon() -> None:
    ip        = get_local_ip()
    now       = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message   = (
        f"📡 Le Potato bot is ONLINE\n"
        f"🕐 Time : {now}\n"
        f"🌐 IP   : {ip}\n"
        f"Type !help for available commands."
    )
    send_message(message)


# ── Entry point ──────────────────────────────

if __name__ == "__main__":
    send_homing_beacon()
    # Bind to all interfaces so ngrok can reach it
    app.run(host="0.0.0.0", port=5000, debug=False)
