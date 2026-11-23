import re
import socket

from pytest_glow import net

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# a non-blocking connect returns at once: nothing goes out, offline or not
ONLINE = """
import socket

def reach(host, port):
    s = socket.socket()
    s.setblocking(False)
    s.connect_ex((host, port))
    s.close()

def test_api(): reach("8.8.8.8", 443)
def test_api_again(): reach("8.8.8.8", 443)
def test_db(): reach("127.0.0.1", 5432)
def test_docker(): reach("172.17.0.2", 5432)
def test_pure(): pass
"""


def test_only_public_addresses_count():
    assert net._public("8.8.8.8") and net._public("2606:4700::1111")
    for local in (
        "127.0.0.1",
        "::1",
        "10.0.0.5",
        "192.168.1.1",
        "172.17.0.2",
        "169.254.1.1",
        "0.0.0.0",
        "fe80::1%eth0",
    ):
        assert not net._public(local), local
    assert not net._public("not an address")


def test_watcher_names_what_it_looked_up():
    watcher = net.Watcher()
    try:
        watcher._names["8.8.8.8"] = "dns.google"
        watcher.pytest_runtest_logstart()
        watcher._saw(socket.socket(), ("8.8.8.8", 53))
        watcher._saw(socket.socket(), ("127.0.0.1", 53))
        assert list(watcher._seen) == ["dns.google:53"]
    finally:
        watcher.restore()
    assert socket.socket.connect is watcher._connect


def run(pytester, *args):
    result = pytester.runpytest_subprocess("--glow", "-p", "no:randomly", *args)
    return ANSI.sub("", result.stdout.str())


def test_tests_that_go_online(pytester):
    pytester.makepyfile(test_n=ONLINE)
    out = run(pytester)
    assert "🌐 2 tests go online" in out
    assert re.search(r"8\.8\.8\.8:443\s+test_api \+1", out)
    assert "5432" not in out  # local and private addresses don't count


def test_no_network_no_word(pytester):
    pytester.makepyfile(test_n="def test_pure(): pass\n")
    assert "online" not in run(pytester)


def test_tests_that_go_online_under_xdist(pytester):
    import pytest

    pytest.importorskip("xdist")
    pytester.makepyfile(test_n=ONLINE)
    assert "🌐 2 tests go online" in run(pytester, "-n", "2")


def test_the_standard_report_doesnt_watch(pytester):
    pytester.makepyfile(
        test_n=ONLINE
        + "\ndef test_unpatched():\n    assert socket.socket.connect is socket.socket.__mro__[1].connect\n"
    )
    assert pytester.runpytest_subprocess("--no-glow").ret == 0
