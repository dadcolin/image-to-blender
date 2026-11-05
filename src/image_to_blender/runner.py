# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded child processes; cancellation kills only this invocation's children."""
import math
import os
from pathlib import Path
import subprocess
import signal
import sys
import time

import psutil
from .validation import write_json_new


def alive(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def guarded(argv, folder, phase, *, max_memory_gib=1.5, min_available_gib=2,
            timeout_seconds=600):
    for value in (max_memory_gib, min_available_gib, timeout_seconds):
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Resource limits must be finite and positive")
    folder = Path(folder)
    if psutil.virtual_memory().available < min_available_gib * 2**30:
        raise MemoryError("Insufficient available memory before worker launch")
    started, peak, code, reason = time.monotonic(), 0, None, None
    child, tracked, caught, cleanup_errors, job = None, {}, None, [], None
    with (folder / (phase + ".log")).open("x", encoding="utf-8") as log:
        try:
            if os.name == "nt":
                from .containment import WindowsJob
                job = WindowsJob()
            command = ([sys.executable, "-B", "-m", "image_to_blender.worker_gate", *argv] if job else argv)
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.PIPE if job else subprocess.DEVNULL,
                                     text=True, start_new_session=os.name != "nt",
                                     env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            owned = psutil.Process(child.pid)
            if job:
                job.assign(child.pid)
                child.stdin.write("start\n")
                child.stdin.flush()
                child.stdin.close()
            while child.poll() is None:
                try:
                    descendants = owned.children(recursive=True)
                    tracked.update((p.pid, p) for p in descendants)
                    rss = owned.memory_info().rss
                    for p in descendants:
                        try:
                            rss += p.memory_info().rss
                        except psutil.NoSuchProcess:
                            pass
                except psutil.NoSuchProcess:
                    break
                peak = max(peak, rss)
                if rss > max_memory_gib * 2**30:
                    reason = "worker_memory_limit"
                elif psutil.virtual_memory().available < min_available_gib * 2**30:
                    reason = "available_memory_floor"
                elif time.monotonic() - started > timeout_seconds:
                    reason = "timeout"
                if reason:
                    break
                time.sleep(0.25)
            if not reason:
                code = child.wait(timeout=5)
        except BaseException as error:
            caught = error
            reason = "cancelled" if isinstance(error, KeyboardInterrupt) else "monitor_error"
        finally:
            if child is not None and not reason and not caught:
                # A successful worker may not leave a background child behind.
                try:
                    _, remaining = psutil.wait_procs(list(tracked.values()), timeout=1)
                    contained_alive = bool(job.active_count()) if job else False
                    if not job:
                        try:
                            os.killpg(child.pid, 0)
                            contained_alive = True
                        except ProcessLookupError:
                            pass
                    if any(alive(p) for p in remaining) or contained_alive:
                        reason = "worker_left_background_child"
                except BaseException as error:
                    caught, reason = error, "containment_check_error"
            if child is not None and (reason or caught):
                try:
                    if job:
                        job.terminate()
                    elif os.name != "nt":
                        os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as error:
                    cleanup_errors.append(type(error).__name__)
                try:
                    tracked.update((p.pid, p) for p in owned.children(recursive=True))
                except (psutil.Error, UnboundLocalError):
                    pass
                for process in reversed(list(tracked.values())):
                    try:
                        process.kill()
                    except psutil.NoSuchProcess:
                        pass
                    except psutil.Error as error:
                        cleanup_errors.append(type(error).__name__)
                if child.poll() is None:
                    child.kill()
                code = child.wait(timeout=10)
                if tracked:
                    _, remaining = psutil.wait_procs(list(tracked.values()), timeout=5)
                    if remaining:
                        cleanup_errors.append("descendant_still_running")
            if job:
                job.close()
    report = {"phase": phase, "elapsed_seconds": round(time.monotonic() - started, 3),
              "peak_rss_bytes_sampled": peak, "exit_code": code, "abort": reason,
              "cleanup_errors": cleanup_errors, "automatic_retry": False,
              "containment": "Windows_job_gated_start" if os.name == "nt" else "POSIX_new_session_process_group",
              "timeout_seconds": timeout_seconds, "memory_limit_covers_gpu_allocations": False}
    write_json_new(folder / (phase + "-resource.json"), report)
    if caught:
        raise caught
    if reason or code or cleanup_errors:
        raise RuntimeError("Worker failed: " + phase + "; inspect its local log (may contain local paths)")
    return report
