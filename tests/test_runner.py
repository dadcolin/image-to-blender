# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
import psutil
import pytest
from image_to_blender.runner import guarded


def test_worker_timeout_reaps_process(tmp_path):
    script = "import os,time; print(os.getpid(), flush=True); time.sleep(30)"
    with pytest.raises(RuntimeError, match="Worker failed"):
        guarded([sys.executable, "-B", "-c", script], tmp_path, "timeout", timeout_seconds=0.6,
                min_available_gib=0.05)
    pid = int((tmp_path / "timeout.log").read_text().strip())
    assert not psutil.pid_exists(pid)
    record = json.loads((tmp_path / "timeout-resource.json").read_text())
    assert record["abort"] == "timeout"
    assert record["automatic_retry"] is False


def test_normal_exit_cannot_leave_tracked_child(tmp_path):
    script = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid,flush=True); time.sleep(1)"
    with pytest.raises(RuntimeError, match="Worker failed"):
        guarded([sys.executable, "-B", "-c", script], tmp_path, "orphan", timeout_seconds=5,
                min_available_gib=0.05)
    pid = int((tmp_path / "orphan.log").read_text().strip())
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    assert json.loads((tmp_path / "orphan-resource.json").read_text())["abort"] == "worker_left_background_child"


def test_fast_exit_child_is_contained_between_polls(tmp_path):
    script = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); print(p.pid,flush=True)"
    with pytest.raises(RuntimeError, match="Worker failed"):
        guarded([sys.executable, "-B", "-c", script], tmp_path, "fast", timeout_seconds=5,
                min_available_gib=0.05)
    pid = int((tmp_path / "fast.log").read_text().strip())
    assert not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    report = json.loads((tmp_path / "fast-resource.json").read_text())
    assert report["abort"] == "worker_left_background_child"
