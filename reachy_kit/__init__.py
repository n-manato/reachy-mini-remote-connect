"""Reachy Mini over the campus VPN: SSH tunnel, SDK media over the tunnel, app launcher.

Students normally only touch my_app.py; see README.md.
"""

__all__ = ["TunnelMedia", "TunnelReachyMini", "connect", "play_sound"]


def __getattr__(name: str):
    # Imported lazily: reachy_kit.remote pulls in the whole SDK (several seconds),
    # which the launcher's early checks and the tunnel CLI do not need.
    if name in __all__:
        from . import remote

        return getattr(remote, name)
    raise AttributeError(f"module 'reachy_kit' has no attribute {name!r}")
