"""Set up robot_config.json and test the connection (run by setup.bat / configure.bat).

The easiest way is a connection code from the instructor (admin/make_code.py):
one line that holds the robot's name, IP and login. Details can also be typed in.

The test needs GlobalProtect to be connected; which Wi-Fi the PC uses does not
matter, only that traffic to the robot goes through the VPN.

    .venv\\Scripts\\python.exe -m reachy_kit.configure
"""

import base64
import getpass
import ipaddress
import json
import os
import sys

from .netcheck import robot_unreachable_reason

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "robot_config.json")
CODE_PREFIX = "reachy1:"
DEFAULTS = {"ssh_user": "pollen", "isolated_subnet": "", "volume": 100,
            "webcam": {"width": 640, "height": 360, "fps": 8}}


def encode_code(cfg: dict) -> str:
    """Connection code for students (used by admin/make_code.py)."""
    keys = ("name", "ip", "ssh_user", "ssh_password", "isolated_subnet")
    data = json.dumps({k: cfg[k] for k in keys if cfg.get(k)}, separators=(",", ":"))
    return CODE_PREFIX + base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def decode_code(code: str) -> dict:
    code = code.strip()
    if not code.startswith(CODE_PREFIX):
        raise ValueError(f"a connection code starts with {CODE_PREFIX!r}")
    body = code[len(CODE_PREFIX):]
    data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    missing = [k for k in ("name", "ip", "ssh_password") if not data.get(k)]
    if missing:
        raise ValueError(f"the code is missing {', '.join(missing)}")
    return data


def ask(prompt: str, default: str = "") -> str:
    shown = f"{prompt} [{default}]: " if default else f"{prompt}: "
    try:
        answer = input(shown).strip()
    except EOFError:  # no console (e.g. started without a window): do not loop forever
        print()
        sys.exit("No input available: run configure.bat from its own window.")
    return answer or default


def enter_details(current: dict) -> dict:
    print("\nEnter the robot details from your instructor.")
    while True:
        cfg = {
            "name": ask("Robot name (e.g. reachy-mini-2)", current.get("name", "")),
            "ip": ask("Robot IP address", current.get("ip", "")),
            "ssh_user": ask("SSH user", current.get("ssh_user", "pollen")),
        }
        try:
            ipaddress.ip_address(cfg["ip"])
        except ValueError:
            print(f"  '{cfg['ip']}' is not an IP address, try again.")
            continue
        pw = getpass.getpass("SSH password (not shown while typing): ") if sys.stdin.isatty() else ask("SSH password")
        cfg["ssh_password"] = pw or current.get("ssh_password", "")
        if cfg["name"] and cfg["ssh_password"]:
            return cfg
        print("  Name and password are required.")


def test_connection(cfg: dict) -> bool:
    """VPN route, SSH login and robot daemon, with a hint for each failure."""
    ip = cfg["ip"]
    print(f"\nTesting the connection to {cfg['name']} ({ip})...")

    # 1. Reached through the VPN (whatever Wi-Fi this PC is on), SSH port open
    reason = robot_unreachable_reason(ip, cfg.get("isolated_subnet", ""))
    if reason:
        print(f"  [NG] {reason}")
        return False
    print("  [OK] The robot is reachable through the VPN.")

    # 2. Login and robot software
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username=cfg.get("ssh_user", "pollen"), password=cfg["ssh_password"],
                       timeout=15, allow_agent=False, look_for_keys=False)
    except paramiko.AuthenticationException:
        print("  [NG] Login failed: wrong SSH user or password.")
        return False
    except Exception as e:
        print(f"  [NG] SSH connection failed: {e}")
        return False
    try:
        _, out, _ = client.exec_command(
            "curl -s -m 5 http://127.0.0.1:8000/api/daemon/status || echo none", timeout=20)
        reply = out.read().decode(errors="replace").strip()
    finally:
        client.close()
    print("  [OK] Logged in to the robot.")
    try:
        state = json.loads(reply).get("state")
    except ValueError:
        state = None
    if state != "running":
        print(f"  [NG] The robot software is not running (state: {state}). Ask your instructor to restart the robot.")
        return False
    print("  [OK] The robot software is running.")
    return True


def save(cfg: dict) -> None:
    merged = {**DEFAULTS, **cfg}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")
    print(f"\nSaved {CONFIG_PATH}")


def main() -> int:
    current = {}
    if os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            current = json.load(f)
        if current.get("ssh_password") in (None, "", "ASK-YOUR-INSTRUCTOR", "ASK-THE-ROBOT-ADMIN"):
            current = {}
        else:
            print(f"Current robot: {current.get('name')} ({current.get('ip')})")
            if ask("Keep it? (Y/n)", "y").lower().startswith("y"):
                return 0 if test_connection(current) else 1

    print("Paste the connection code from your instructor and press Enter.")
    print("(No code? Just press Enter to type the details instead.)")
    while True:
        code = ask("Connection code")
        if not code:
            cfg = enter_details(current)
            break
        try:
            cfg = decode_code(code)
            break
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"  That code did not work ({e}). Copy the whole line and try again.")

    save({**{k: v for k, v in current.items() if k in ("volume", "webcam")}, **cfg})
    ok = test_connection(cfg)
    if ok:
        print("\nAll set. Double-click run.bat to start.")
    else:
        print("\nThe settings were saved, but the test failed. Fix the problem above,")
        print("then run configure.bat again (or just run.bat to retry).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
