"""Connect a Reachy Mini's USB Wi-Fi adapter (wlan1) to eduroam.

The lab Wi-Fi on wlan0 has no internet, so eduroam (wlan1) carries the
default route and wlan0 is only used for the local lab network.

Usage (PC on the lab Wi-Fi, robots reached by their lab IPs):
    $env:EDUROAM_IDENTITY="user@example.edu"
    $env:EDUROAM_PASSWORD="..."
    $env:REACHY_PASSWORD="..."         # robot SSH password
    python setup_eduroam.py <robot lab IP> [<robot lab IP> ...]

Options via env:
    EDUROAM_DOMAIN_MATCH   RADIUS server certificate domain (domain-suffix-match)
    LAN_CONNECTION         NetworkManager name of the lab Wi-Fi connection on
                           wlan0; it is set to never-default (LAN only)
"""

import io
import os
import sys
import time

import paramiko

ROBOT_PASSWORD = os.environ.get("REACHY_PASSWORD", "")
IDENTITY = os.environ.get("EDUROAM_IDENTITY", "")
DOMAIN_MATCH = os.environ.get("EDUROAM_DOMAIN_MATCH", "")
LAN_CONNECTION = os.environ.get("LAN_CONNECTION", "")
HERE = os.path.dirname(os.path.abspath(__file__))
DISPATCHER = os.path.join(HERE, "robot", "60-eduroam-policy-route")


def keyfile(password: str) -> str:
    realm = IDENTITY.split("@", 1)[1]
    domain_line = f"domain-suffix-match={DOMAIN_MATCH}\n" if DOMAIN_MATCH else ""
    return f"""[connection]
id=eduroam
type=wifi
interface-name=wlan1
autoconnect=true
autoconnect-retries=0

[wifi]
mode=infrastructure
ssid=eduroam

[wifi-security]
key-mgmt=wpa-eap

[802-1x]
eap=peap;
identity={IDENTITY}
anonymous-identity=anonymous@{realm}
ca-cert=/etc/ssl/certs/ca-certificates.crt
{domain_line}phase2-auth=mschapv2
password={password}

[ipv4]
method=auto
route-metric=100

[ipv6]
method=disabled
"""


def run(c: paramiko.SSHClient, cmd: str, timeout: int = 60) -> str:
    stdin, stdout, stderr = c.exec_command(f"sudo -S -p '' sh -c '{cmd}'", timeout=timeout)
    stdin.write(ROBOT_PASSWORD + "\n")
    stdin.flush()
    return (stdout.read() + stderr.read()).decode().strip()


def setup(ip: str, password: str) -> None:
    print(f"########## {ip}")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(ip, username="pollen", password=ROBOT_PASSWORD, timeout=10,
              allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    sftp.putfo(io.BytesIO(keyfile(password).encode()), "/tmp/eduroam.nmconnection")
    with open(DISPATCHER, "rb") as f:  # strip CRLF from Windows checkouts
        sftp.putfo(io.BytesIO(f.read().replace(b"\r\n", b"\n")), "/tmp/60-eduroam-policy-route")
    sftp.close()

    run(c, "install -m 600 -o root -g root /tmp/eduroam.nmconnection "
           "/etc/NetworkManager/system-connections/eduroam.nmconnection && rm -f /tmp/eduroam.nmconnection")
    run(c, "install -m 755 -o root -g root /tmp/60-eduroam-policy-route "
           "/etc/NetworkManager/dispatcher.d/60-eduroam-policy-route && rm -f /tmp/60-eduroam-policy-route")
    run(c, "nmcli connection reload")
    if LAN_CONNECTION:
        # The lab Wi-Fi has no internet: keep it for the local network only.
        run(c, f"nmcli connection modify \"{LAN_CONNECTION}\" ipv4.never-default yes && nmcli device reapply wlan0")
    print("activate:", run(c, "nmcli --wait 60 connection up eduroam ifname wlan1 2>&1 | tail -2", timeout=90))
    time.sleep(3)
    print(run(c, "nmcli -t -f DEVICE,STATE,CONNECTION device | grep wlan"))
    print("wlan1:", run(c, "ip -4 -o addr show wlan1 | awk \"{print \\$4}\""))
    print(run(c, "ip rule show pref 1001; ip route show table 101; ip route show default"))
    print("internet:", run(c, "curl -s -o /dev/null -w \"%{http_code} via %{local_ip}\" --max-time 8 https://huggingface.co || echo FAIL"))
    print("server cert:", run(c, "journalctl -u wpa_supplicant -u NetworkManager --since -3min --no-pager "
                                 "| grep -iE \"EAP-PEER-CERT depth=0|subject=|EAP-FAILURE|EAP-SUCCESS|reject\" | tail -4"))
    c.close()


def main() -> None:
    password = os.environ.get("EDUROAM_PASSWORD")
    if not (password and IDENTITY and ROBOT_PASSWORD) or len(sys.argv) < 2:
        sys.exit(__doc__)
    for ip in sys.argv[1:]:
        setup(ip, password)


if __name__ == "__main__":
    main()
