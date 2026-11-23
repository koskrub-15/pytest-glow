import sys, threading, time
from pytest_glow.profile import Sampler

def test_diag(capsys):
    s = Sampler(".", ["test_*.py"])
    s.begin()
    end = time.perf_counter() + 0.5
    while time.perf_counter() < end:
        pass
    got = s.end()
    s.stop()
    # and how fast a plain sleeping thread ticks next to a busy one
    ticks = []
    stop = threading.Event()
    def tick():
        while not stop.wait(0.005):
            ticks.append(time.perf_counter())
    t = threading.Thread(target=tick, daemon=True); t.start()
    end = time.perf_counter() + 0.5
    while time.perf_counter() < end:
        pass
    stop.set(); t.join()
    with capsys.disabled():
        print(f"\nDIAG {sys.platform} {sys.version.split()[0]} switch={sys.getswitchinterval()} sampler={got} ticks={len(ticks)}")
