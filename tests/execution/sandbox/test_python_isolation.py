"""Isolation and resource limits, checked by running real code in real containers."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_no_network(sandbox):
    result = sandbox.run(
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except OSError as e:\n"
        "    print('BLOCKED', type(e).__name__)\n"
    )
    assert result.ok, result.to_dict()
    assert "BLOCKED" in result.stdout and "CONNECTED" not in result.stdout


def test_root_filesystem_is_read_only(sandbox):
    result = sandbox.run(
        "for path in ('/etc/x', '/x', '/usr/x'):\n"
        "    try:\n"
        "        open(path, 'w').write('hi')\n"
        "        print('WROTE', path)\n"
        "    except OSError as e:\n"
        "        print('DENIED', path, e.errno)\n"
    )
    assert result.ok, result.to_dict()
    assert "WROTE" not in result.stdout
    assert result.stdout.count("DENIED") == 3


def test_runs_as_unprivileged_user_without_capabilities(sandbox):
    result = sandbox.run(
        "import os\n"
        "print(os.getuid(), os.getgid())\n"
        "caps = [l for l in open('/proc/self/status') if l.startswith('CapEff')][0]\n"
        "print(caps.split()[1])\n"
    )
    assert result.ok, result.to_dict()
    uid_gid, caps = result.stdout.split("\n")[:2]
    assert uid_gid == "65534 65534"
    assert int(caps, 16) == 0


def test_tmp_is_writable(sandbox):
    result = sandbox.run("open('/tmp/f.txt', 'w').write('data')\nprint(open('/tmp/f.txt').read())")
    assert result.ok, result.to_dict()
    assert result.stdout == "data\n"


def test_memory_limit_is_enforced(sandbox):
    # Touch 512 MB against a 256 MB limit.
    result = sandbox.run("blob = b'x' * (512 * 1024 * 1024)\nprint(len(blob))", timeout_s=30)
    assert not result.ok
    assert result.oom_killed or result.exit_code == 137 or result.error_type == "MemoryError"
    assert "536870912" not in result.stdout


def test_process_limit_is_enforced(sandbox):
    result = sandbox.run(
        "import subprocess\n"
        "procs = []\n"
        "try:\n"
        "    for _ in range(200):\n"
        "        procs.append(subprocess.Popen(['sleep', '30']))\n"
        "    print('SPAWNED_ALL')\n"
        "except Exception as e:\n"
        "    print('SPAWN_FAILED', len(procs), type(e).__name__)\n"
        "finally:\n"
        "    for p in procs:\n"
        "        p.kill()\n",
        timeout_s=30,
    )
    assert result.ok, result.to_dict()
    assert "SPAWN_FAILED" in result.stdout and "SPAWNED_ALL" not in result.stdout


def test_host_files_are_not_visible(sandbox):
    result = sandbox.run(
        "import os\n"
        f"print(os.path.exists({str(REPO_ROOT)!r}))\n"
        f"print(os.path.exists({str(REPO_ROOT / 'pyproject.toml')!r}))\n"
        "print(os.listdir('/home'), os.path.exists('/var/run/docker.sock'))\n"
    )
    assert result.ok, result.to_dict()
    assert result.stdout.split("\n")[:3] == ["False", "False", "[] False"]


def test_infinite_loop_is_killed_by_the_timeout(sandbox):
    result = sandbox.run("while True: pass", timeout_s=2)
    assert result.timed_out is True
    assert result.error_type == "Timeout"
    assert result.duration_s < 10


def test_error_comes_back_with_its_traceback(sandbox):
    result = sandbox.run("print(undefined_var)")
    assert result.ok is False
    assert result.error_type == "NameError"
    assert "undefined_var" in result.traceback


def test_output_flood_is_capped(sandbox):
    result = sandbox.run("print('x' * 1_000_000)", timeout_s=20)
    assert result.truncated is True
    assert len(result.stdout.encode()) <= 64 * 1024
