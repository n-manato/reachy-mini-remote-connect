"""Reachy Mini over the campus VPN: SSH tunnel, SDK media over the tunnel, app launcher.

Students normally only touch my_app.py; see README.md.
"""

from .remote import TunnelMedia, TunnelReachyMini, connect, play_sound

__all__ = ["TunnelMedia", "TunnelReachyMini", "connect", "play_sound"]
