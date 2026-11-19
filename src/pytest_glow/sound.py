"""--glow-sound: chiptune sounds for the run, synthesized here, so there is nothing to license or ship.

Try them all with ``python -m pytest_glow.sound``.
"""

from __future__ import annotations

import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from collections.abc import Callable

RATE = 22050
REVISION = 4  # bump when a sound changes, so the cached files get rebuilt
HIT_GAP = 0.12  # at most this often a hit sound, or a fast suite turns into a drum roll
COMBO_MILESTONES = (10, 25, 50, 100, 250, 500, 1000)

Samples = list[float]


# -- synthesis --------------------------------------------------------------------------


def note(name: str) -> float:
    """'A4' → 440.0; sharps as 'C#5'."""
    steps = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    semis = steps[name[0]] + (1 if "#" in name else 0) + 12 * (int(name[-1]) - 4)
    return 440.0 * 2 ** (semis / 12)


def _osc(shape: str, phase: float) -> float:
    p = phase % 1.0
    if shape == "square":
        return 1.0 if p < 0.5 else -1.0
    if shape == "pulse":
        return 1.0 if p < 0.25 else -1.0
    if shape == "saw":
        return 2 * p - 1
    if shape == "tri":
        return 4 * abs(p - 0.5) - 1
    return math.sin(2 * math.pi * p)


def lowpass(samples: Samples, cutoff: float) -> Samples:
    """One-pole filter: takes the buzz off squares and saws."""
    dt = 1 / RATE
    a = dt / (1 / (2 * math.pi * cutoff) + dt)
    out, y = [], 0.0
    for x in samples:
        y += a * (x - y)
        out.append(y)
    return out


def tone(
    freq: float,
    dur: float,
    shape: str = "square",
    vol: float = 0.3,
    *,
    to: float | None = None,
    attack: float = 0.005,
    release: float = 0.03,
    vibrato: float = 0.0,
    cutoff: float | None = 3000,
) -> Samples:
    n = int(dur * RATE)
    end = to or freq
    out, phase = [], 0.0
    for i in range(n):
        f = freq * (end / freq) ** (i / n)  # exponential slide, like a pitch bend
        if vibrato:
            f *= 1 + vibrato * math.sin(2 * math.pi * 5.5 * i / RATE)
        phase += f / RATE
        env = min(1.0, i / (attack * RATE + 1), (n - i) / (release * RATE + 1))
        out.append(_osc(shape, phase) * vol * env)
    return lowpass(out, cutoff) if cutoff else out


def noise(dur: float, vol: float = 0.3, decay: float = 10.0, cutoff: float = 2500, seed: int = 7) -> Samples:
    rng = random.Random(seed)
    n = int(dur * RATE)
    attack = 0.003 * RATE  # no click at the start
    return lowpass(
        [rng.uniform(-1, 1) * vol * min(1, i / attack) * math.exp(-decay * i / RATE) for i in range(n)], cutoff
    )


def rest(dur: float) -> Samples:
    return [0.0] * int(dur * RATE)


def seq(*parts: Samples) -> Samples:
    return [x for part in parts for x in part]


def mix(*tracks: Samples) -> Samples:
    out = [0.0] * max(map(len, tracks))
    for track in tracks:
        for i, x in enumerate(track):
            out[i] += x
    return out


# -- the sounds ------------------------------------------------------------------------


def level_clear() -> Samples:
    """A green run: a quick arpeggio up and a bright chord, the end-of-level jingle."""
    run = seq(*(tone(note(n), 0.07, "pulse", 0.22) for n in ("C5", "E5", "G5", "C6", "E6")))
    chord = mix(*(tone(note(n), 0.45, "square", 0.1, vibrato=0.004, release=0.25) for n in ("C6", "E6", "G6")))
    bass = seq(rest(0.35), tone(note("C3"), 0.45, "tri", 0.35, release=0.25, cutoff=None))
    return mix(seq(run, chord), bass)


def level_up() -> Samples:
    """A level up: two climbing runs and a ringing chord on top."""
    first = [tone(note(n), 0.06, "pulse", 0.22) for n in ("G4", "C5", "E5", "G5")]
    second = [tone(note(n), 0.06, "pulse", 0.22) for n in ("A4", "D5", "F#5", "A5")]
    ring = mix(
        *(tone(note(n), 0.7, "square", 0.09, vibrato=0.006, release=0.45) for n in ("D6", "F#6", "A6")),
        tone(note("D3"), 0.7, "tri", 0.35, release=0.45, cutoff=None),
    )
    return seq(*first, rest(0.03), *second, ring)


def shiny() -> Samples:
    """A shiny run: a sparkle up and down, then a shimmer."""
    up = [tone(note(n), 0.05, "pulse", 0.18) for n in ("E6", "G#6", "B6", "E7")]
    down = [tone(note(n), 0.05, "tri", 0.2, cutoff=None) for n in ("B6", "G#6", "B6", "E7")]
    shimmer = mix(
        *(tone(note(n), 0.9, "tri", 0.12, vibrato=0.01, release=0.7, cutoff=None) for n in ("E6", "B6", "E7"))
    )
    return seq(*up, *down, shimmer)


def sad_trombone() -> Samples:
    """A red run: wah, wah, wah, waaaah."""
    wahs = [
        tone(note(n), 0.36, "saw", 0.45, attack=0.04, release=0.12, cutoff=1100) + rest(0.04)
        for n in ("D4", "C#4", "C4")
    ]
    last = tone(note("B3"), 1.1, "saw", 0.45, to=note("A#3"), attack=0.04, release=0.35, vibrato=0.02, cutoff=1100)
    return seq(*wahs, last)


def airhorn() -> Samples:
    """A record or an achievement: BWAA BWAA BWAA BWAAAAAAA."""

    def blast(dur: float) -> Samples:
        return mix(
            *(
                tone(f, dur, "saw", 0.17, to=f * 0.97, attack=0.01, release=0.05, cutoff=3200)
                for f in (415.0, 419.0, 830.0, 623.0)
            )
        )

    return seq(blast(0.13), rest(0.05), blast(0.13), rest(0.05), blast(0.13), rest(0.05), blast(0.8))


def combo(level: int) -> Samples:
    """A combo milestone: a power-up arpeggio, a step higher every milestone."""
    root = note("C5") * 2 ** (min(level, 6) * 2 / 12)
    steps = (0, 4, 7, 12, 16) if level >= 3 else (0, 4, 7, 12)
    notes = [tone(root * 2 ** (s / 12), 0.045, "pulse", 0.28) for s in steps]
    sparkle = tone(root * 4, 0.12, "tri", 0.25, to=root * 4.5, release=0.1, cutoff=None)
    return seq(*notes, sparkle)


def combo_breaker() -> Samples:
    """A failure ends a combo: the long slide down."""
    return mix(tone(660, 0.45, "square", 0.22, to=90, release=0.1, cutoff=2000), seq(rest(0.38), noise(0.15, 0.2)))


def hit() -> Samples:
    """A test lands a hit on the boss: a thump and a crack."""
    return mix(tone(200, 0.09, "square", 0.18, to=55, cutoff=1400), noise(0.06, 0.2, decay=45, cutoff=3500))


def crit() -> Samples:
    """A hit during a combo: the same, with a zing on top."""
    return mix(hit(), seq(rest(0.02), tone(note("E6"), 0.07, "pulse", 0.12, to=note("B6"), cutoff=None)))


def hurt() -> Samples:
    """The boss hits you."""
    return mix(tone(480, 0.16, "square", 0.25, to=180, cutoff=1800), noise(0.1, 0.25, decay=25, cutoff=1500))


def boss_down() -> Samples:
    """Victory: an explosion, then the fanfare."""
    boom = mix(noise(0.9, 0.5, decay=5, cutoff=900, seed=3), tone(90, 0.5, "tri", 0.4, to=35, cutoff=None))
    melody = seq(
        *(
            tone(note(n), d, "square", 0.16, release=0.02)
            for n, d in (("G4", 0.1), ("C5", 0.1), ("E5", 0.1), ("G5", 0.2), ("E5", 0.1))
        ),
        tone(note("G5"), 0.6, "square", 0.16, vibrato=0.006, release=0.3),
    )
    bass = seq(rest(0.6), tone(note("C3"), 0.6, "tri", 0.35, release=0.3, cutoff=None))
    return seq(boom[: int(0.45 * RATE)], mix(melody, bass))


def game_over() -> Samples:
    """The boss wins."""
    return seq(
        *(tone(note(n), 0.26, "pulse", 0.2, release=0.06) for n in ("G4", "D4", "B3")),
        tone(note("G3"), 0.9, "tri", 0.4, to=note("F#3"), vibrato=0.015, release=0.4, cutoff=None),
    )


SOUNDS: dict[str, Callable[[], Samples]] = {
    "level_clear": level_clear,
    "level_up": level_up,
    "shiny": shiny,
    "sad_trombone": sad_trombone,
    "airhorn": airhorn,
    "combo_breaker": combo_breaker,
    "hit": hit,
    "crit": crit,
    "hurt": hurt,
    "boss_down": boss_down,
    "game_over": game_over,
    **{f"combo{level}": (lambda level=level: combo(level)) for level in range(len(COMBO_MILESTONES))},
}


# -- files and players -----------------------------------------------------------------


def _cache_dir() -> str:
    user = os.getuid() if hasattr(os, "getuid") else os.environ.get("USERNAME", "")
    return os.path.join(tempfile.gettempdir(), f"pytest-glow-{user}-sounds-v{REVISION}")


def wav_bytes(samples: Samples) -> bytes:
    peak = max(1.0, *map(abs, samples)) if samples else 1.0
    return b"".join(int(x / peak * 32767).to_bytes(2, "little", signed=True) for x in samples)


def path_for(name: str) -> str:
    """The WAV file for a sound, synthesized the first time it's needed."""
    path = os.path.join(_cache_dir(), f"{name}.wav")
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(wav_bytes(SOUNDS[name]()))
    os.replace(tmp, path)
    return path


def command(path: str) -> list[str] | None:
    if sys.platform == "darwin":
        players = ("afplay",)
    else:
        players = ("pw-play", "paplay", "aplay")
    for player in players:
        if shutil.which(player):
            return [player, "-q", path] if player == "aplay" else [player, path]
    return None


def _spawn(path: str) -> bool:
    if sys.platform == "win32":
        try:
            import winsound

            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return True
        except (ImportError, RuntimeError):
            return False
    cmd = command(path)
    if cmd is None:
        return False
    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


class Player:
    """Plays sounds without ever making pytest wait for them."""

    def __init__(self, stream) -> None:
        self.stream = stream
        self._last_hit = 0.0
        # synthesize everything up front, off the main thread
        threading.Thread(target=self._warm, daemon=True).start()

    def _warm(self) -> None:
        for name in SOUNDS:
            try:
                path_for(name)
            except OSError:
                return

    def play(self, name: str, *, bell: bool = False) -> None:
        """``bell``: ring the terminal bell when there's no way to play it (only for the final sound)."""
        try:
            played = _spawn(path_for(name))
        except OSError:
            played = False
        if not played and bell:
            self.stream.write("\a")
            self.stream.flush()

    def hit(self, crit: bool) -> None:
        now = time.monotonic()
        if now - self._last_hit >= HIT_GAP:
            self._last_hit = now
            self.play("crit" if crit else "hit")


def milestone(combo: int) -> int | None:
    """The milestone index when a combo has just reached one."""
    return COMBO_MILESTONES.index(combo) if combo in COMBO_MILESTONES else None


if __name__ == "__main__":
    names = sys.argv[1:] or list(SOUNDS)
    for name in names:
        print(f"♪ {name}  {SOUNDS[name].__doc__ or ''}".rstrip())
        path = path_for(name)
        if not _spawn(path):
            print(f"  no player found; the file is {path}")
        with wave.open(path) as w:
            time.sleep(w.getnframes() / RATE + 0.35)
