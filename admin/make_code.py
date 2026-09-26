"""Print the connection code students paste into setup.bat / configure.bat.

    .venv\\Scripts\\python.exe admin\\make_code.py NAME IP [--user pollen] [--subnet 10.0.0.0/18]

The SSH password is asked for (not taken from the command line, so it does
not end up in the shell history). The code only encodes the values; share it
with students the same way you would share the password.
"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root

from reachy_kit.configure import encode_code  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name", help="robot name shown to students, e.g. reachy-mini-2")
    p.add_argument("ip", help="robot eduroam IP address")
    p.add_argument("--user", default="pollen", help="SSH user (default: pollen)")
    p.add_argument("--subnet", default="", help="robots' Wi-Fi subnet for the 'not via VPN' check (optional)")
    a = p.parse_args()
    password = os.environ.get("REACHY_PASSWORD") or getpass.getpass("Robot SSH password: ")
    print(encode_code({"name": a.name, "ip": a.ip, "ssh_user": a.user,
                       "ssh_password": password, "isolated_subnet": a.subnet}))


if __name__ == "__main__":
    main()
