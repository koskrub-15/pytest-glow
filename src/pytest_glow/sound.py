"""--glow-sound: a sound when the run ends. The system's own sounds, else the terminal bell."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

_MAC = "/System/Library/Sounds"
_FREEDESKTOP = "/usr/share/sounds/freedesktop/stereo"
SOUNDS = {
    # kind -> (macOS sound, freedesktop sound)
    "green": ("Glass.aiff", "complete.oga"),
    "red": ("Basso.aiff", "dialog-error.oga"),
    "fanfare": ("Hero.aiff", "service-login.oga"),
}


def command(kind: str) -> list[str] | None:
    mac, linux = SOUNDS.get(kind, SOUNDS["green"])
    if sys.platform == "darwin" and shutil.which("afplay"):
        path = os.path.join(_MAC, mac)
        return ["afplay", path] if os.path.exists(path) else None
    path = os.path.join(_FREEDESKTOP, linux)
    if not os.path.exists(path):
        return None
    for player in ("pw-play", "paplay"):
        if shutil.which(player):
            return [player, path]
    return None


def play(kind: str, stream) -> None:
    """Fire and forget: pytest doesn't wait for the sound to finish."""
    cmd = command(kind)
    if cmd is not None:
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        except OSError:
            pass
    stream.write("\a")
    stream.flush()
