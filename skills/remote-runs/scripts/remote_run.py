#!/usr/bin/env python3
"""Cooperative Linux CPU/GPU admission and descendant-aware run supervision.

Claims are durable reservations, not lifetime flock descriptors. A killed
supervisor intentionally leaves a reservation for conservative recovery.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import fcntl
import grp
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

import resource_probe as rp

VERSION = 1
THREAD_VARIABLES = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "JULIA_NUM_THREADS", "RAYON_NUM_THREADS",
    "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
)
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")


class RunError(RuntimeError):
    pass


class BusyError(RunError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def finite_number(value, *, zero=False, upper=None):
    number = float(value)
    if not math.isfinite(number) or number < 0 or (not zero and number == 0):
        raise argparse.ArgumentTypeError("must be finite and " + ("nonnegative" if zero else "positive"))
    if upper is not None and number > upper:
        raise argparse.ArgumentTypeError(f"must be at most {upper}")
    return number


def nonnegative(value):
    return finite_number(value, zero=True)


def positive(value):
    return finite_number(value)


def percentage(value):
    return finite_number(value, zero=True, upper=100)


def id_value(value):
    if not ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("run ID must be 1-96 letters, digits, underscores or hyphens")
    return value


def cpu_list(value):
    """Parse ranges, rejecting duplicates instead of silently hiding mistakes."""
    answer = []
    if not value:
        raise argparse.ArgumentTypeError("resource list is empty")
    try:
        for piece in value.split(","):
            if not re.fullmatch(r"\d+(?:-\d+)?", piece):
                raise ValueError("use comma-separated nonnegative IDs/ranges")
            if "-" in piece:
                left, right = map(int, piece.split("-"))
                if right < left or right - left > 1_000_000:
                    raise ValueError("invalid resource range")
                answer.extend(range(left, right + 1))
            else:
                answer.append(int(piece))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if len(answer) != len(set(answer)):
        raise argparse.ArgumentTypeError("duplicate resource IDs")
    return answer


def absolute_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("an absolute path is required")
    return path


def directory_sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value, mode=0o600):
    path = Path(path)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = -1
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_sync(path.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def read_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RunError(f"not a regular state file: {path}")
        with os.fdopen(fd, encoding="utf-8") as stream:
            fd = -1
            value = json.load(stream)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(value, dict):
        raise RunError(f"invalid state object: {path}")
    return value


def same_identity(left, right):
    return bool(left and right and all(left.get(key) == right.get(key)
                                      for key in ("pid", "start_ticks", "boot_id", "uid")))


def namespace(state_dir):
    path = Path(state_dir).resolve(strict=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & (stat.S_ISVTX | 0o002):
        raise RunError("state directory must be a trusted, non-sticky, non-world-writable directory")
    config = read_json(path / "config.json")
    if (config.get("version") != VERSION or config.get("host_id") != rp.host_id()
            or type(config.get("memory_budget_mib")) is not int
            or config["memory_budget_mib"] <= 0
            or config.get("file_mode") not in (0o600, 0o660)
            or type(config.get("uid")) is not int or config["uid"] < 0
            or type(config.get("gid")) is not int or config["gid"] < 0):
        raise RunError("namespace configuration is invalid or belongs to a different host")
    if info.st_uid != config.get("uid") or info.st_gid != config.get("gid"):
        raise RunError("namespace ownership differs from its initialization record")
    for name in ("claims", "finished"):
        child = path / name
        if child.is_symlink() or not child.is_dir():
            raise RunError(f"invalid namespace directory: {child}")
        if child.stat().st_mode & (stat.S_ISVTX | 0o002):
            raise RunError(f"unsafe namespace permissions: {child}")
    return path, config


@contextlib.contextmanager
def admission_gate(path, deadline=None, cancel=None):
    gate = path / "admission.lock"
    fd = os.open(gate, os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RunError("admission gate must be one stable regular file")
        while True:
            if cancel is not None and cancel[0] is not None:
                raise RunError("admission cancelled before command startup")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise BusyError("overall admission deadline reached while waiting for the gate")
                time.sleep(min(0.025, max(0.001, deadline - time.monotonic())) if deadline else 0.025)
        if cancel is not None and cancel[0] is not None:
            raise RunError("admission cancelled before command startup")
        current = gate.lstat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise RunError("admission gate inode changed")
        yield
    finally:
        os.close(fd)


def init_namespace(args):
    path = args.state_dir
    if path.exists() or path.is_symlink():
        raise RunError("initialization requires a new state directory")
    gid = os.getegid()
    mode = 0o700
    file_mode = 0o600
    if args.group:
        gid = grp.getgrnam(args.group).gr_gid
        if gid not in {*os.getgroups(), os.getegid()}:
            raise RunError("the requested shared group is not one of this user's groups")
        mode, file_mode = 0o2770, 0o660
    path.mkdir(mode=0o700)
    os.chown(path, -1, gid)
    os.chmod(path, mode)
    for name in ("claims", "finished"):
        child = path / name
        child.mkdir(mode=mode)
        os.chown(child, -1, gid)
        os.chmod(child, mode)
    gate_fd = os.open(path / "admission.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, file_mode)
    os.fchmod(gate_fd, file_mode)
    os.fsync(gate_fd)
    os.close(gate_fd)
    config = {"version": VERSION, "host_id": rp.host_id(), "uid": os.geteuid(),
              "gid": gid, "file_mode": file_mode, "memory_budget_mib": args.memory_budget_mib,
              "created_utc": utc_now()}
    atomic_json(path / "config.json", config, file_mode)
    directory_sync(path)
    emit({"ok": True, "state_dir": str(path.resolve()), "config": config,
          "scope": "participating launches using this namespace"})
    return 0


def validate_claim(value, config, name=None):
    resources = value.get("resources")
    owner = value.get("owner")
    cpus, gpus = value.get("cpus"), value.get("gpus")
    grace = value.get("kill_grace")
    valid_resources = (
        isinstance(resources, list) and resources
        and all(isinstance(item, str) and re.fullmatch(r"(?:cpu:\d+:\d+|gpu:GPU-[A-Za-z0-9-]+)", item)
                for item in resources)
        and len(resources) == len(set(resources))
        and any(item.startswith("cpu:") for item in resources)
    )
    valid_lists = (
        isinstance(cpus, list) and cpus and isinstance(gpus, list)
        and all(type(cpu) is int and cpu >= 0 for cpu in cpus)
        and all(type(gpu) is int and gpu >= 0 for gpu in gpus)
        and len(cpus) == len(set(cpus)) and len(gpus) == len(set(gpus))
    )
    if (value.get("version") != VERSION or value.get("host_id") != config["host_id"]
            or not isinstance(value.get("run_id"), str) or not ID_PATTERN.fullmatch(value["run_id"])
            or (name and name != value["run_id"])
            or not isinstance(value.get("nonce"), str) or not re.fullmatch(r"[0-9a-f]{32}", value["nonce"])
            or not valid_resources or not valid_lists
            or (valid_resources and valid_lists and
                (sum(x.startswith("gpu:") for x in resources) != len(gpus)
                 or sum(x.startswith("cpu:") for x in resources) > len(cpus)))
            or type(value.get("memory_mib")) is not int or value["memory_mib"] <= 0
            or not isinstance(owner, dict)
            or not isinstance(value.get("run_dir"), str) or not Path(value["run_dir"]).is_absolute()
            or type(grace) not in (int, float) or not math.isfinite(grace) or grace < 0):
        raise RunError("malformed reservation claim; admission remains closed")
    if (any(type(owner.get(k)) is not int for k in ("pid", "start_ticks", "uid"))
            or owner["pid"] <= 0 or owner["start_ticks"] < 0 or owner["uid"] < 0
            or not isinstance(owner.get("boot_id"), str) or not owner["boot_id"]):
        raise RunError("malformed claim owner; admission remains closed")
    if value.get("boot_id") != owner["boot_id"]:
        raise RunError("claim boot identity is inconsistent")
    return value


def claims_in(path, config):
    answer = []
    for item in sorted((path / "claims").iterdir()):
        if re.fullmatch(r"\.[A-Za-z0-9][A-Za-z0-9_-]{0,95}\.json\.[0-9a-f]{32}\.tmp", item.name):
            continue  # A pre-publication crash cannot have started the command.
        if item.suffix != ".json" or item.is_symlink():
            raise RunError("unrecognized entry in reservation directory; admission remains closed")
        answer.append(validate_claim(read_json(item), config, item.stem))
    return answer


def mem_available():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            fields = line.split()
            if len(fields) != 3 or fields[2] != "kB" or not fields[1].isdigit():
                break
            return int(fields[1]) * 1024
    raise RunError("MemAvailable is unavailable or malformed")


def gpu_snapshot(args, deadline=None):
    if not args.gpus:
        return {"idle": True, "devices": {}}
    remaining = 10.0 if deadline is None else min(10.0, deadline - time.monotonic())
    if remaining <= 0:
        raise BusyError("overall deadline reached before GPU probe")
    return rp.probe_gpu_idle(args.gpus, max_util_percent=args.max_gpu_util,
                             max_memory_mib=args.max_gpu_memory_mib, timeout=remaining)


def cpu_snapshot(args, cpus, deadline=None):
    if deadline is not None and deadline - time.monotonic() < args.sample_seconds:
        raise BusyError("overall deadline has insufficient time for the CPU sample")
    return rp.probe_cpu_idle(cpus, interval=args.sample_seconds,
                             max_busy_percent=args.max_cpu_busy)


def select_resources(args, used, deadline=None):
    topology = rp.cpu_topology()
    allowed = set(os.sched_getaffinity(0))
    available = sorted(set(topology) & allowed)
    if not available:
        raise RunError("no online CPUs in the current effective affinity")
    if args.cpus:
        if not set(args.cpus) <= set(available):
            raise RunError("requested CPU is offline, unknown or outside effective affinity")
        selected = list(args.cpus)
        physical = {topology[cpu]["resource_id"] for cpu in selected}
        if physical & used:
            raise BusyError("one or more requested physical CPU cores are reserved")
        siblings = sorted({s for cpu in selected for s in topology[cpu]["siblings"]})
        cpu_probe = cpu_snapshot(args, siblings, deadline)
        if not cpu_probe.get("idle"):
            raise BusyError("requested CPUs or their SMT siblings are busy")
    else:
        candidates = {}
        for cpu in available:
            rid = topology[cpu]["resource_id"]
            if rid not in used:
                candidates.setdefault(rid, cpu)
        if len(candidates) < args.cores:
            raise BusyError("insufficient unreserved physical CPU cores")
        siblings = sorted({s for cpu in candidates.values() for s in topology[cpu]["siblings"]})
        cpu_probe = cpu_snapshot(args, siblings, deadline)
        if cpu_probe.get("idle"):
            idle = list(candidates.values())
        else:
            busy = cpu_probe.get("busy_percent", {})
            try:
                idle = [cpu for cpu in candidates.values()
                        if all(float(busy[str(s)]) <= args.max_cpu_busy
                               for s in topology[cpu]["siblings"])]
            except (KeyError, TypeError, ValueError) as exc:
                raise RunError("CPU probe did not cover every candidate sibling") from exc
        if len(idle) < args.cores:
            raise BusyError("insufficient idle physical CPU cores")
        selected = idle[:args.cores]
        physical = {topology[cpu]["resource_id"] for cpu in selected}
    gpu_probe = gpu_snapshot(args, deadline)
    if not gpu_probe.get("idle"):
        raise BusyError("requested GPUs are busy or exceed the declared idle baseline")
    devices = gpu_probe.get("devices", {})
    try:
        gpu_ids = {"gpu:" + devices[str(index)]["uuid"] for index in args.gpus}
    except (KeyError, TypeError) as exc:
        raise RunError("GPU probe did not identify every requested device") from exc
    if gpu_ids & used:
        raise BusyError("one or more requested GPU UUIDs are reserved")
    return selected, sorted(physical | gpu_ids), cpu_probe, gpu_probe


def reserve(args, path, config, owner, run_id, nonce, cancel):
    start = time.monotonic()
    deadline = start + args.wait
    last_error = "resources unavailable"
    while True:
        if cancel[0] is not None:
            raise RunError("admission cancelled before command startup")
        try:
            with admission_gate(path, deadline, cancel=cancel):
                claims = claims_in(path, config)
                if any(item["run_id"] == run_id for item in claims) or (path / "finished" / (run_id + ".json")).exists():
                    raise RunError("run ID already exists; use a fresh run ID")
                if sum(item["memory_mib"] for item in claims) + args.memory_mib > config["memory_budget_mib"]:
                    raise BusyError("declared memory reservation budget is exhausted")
                available_bytes = mem_available()
                if available_bytes < args.memory_mib * 1024 * 1024:
                    raise BusyError("current MemAvailable is below the requested memory budget")
                used = {resource for item in claims for resource in item["resources"]}
                cpus, resources, cpu_probe, gpu_probe = select_resources(
                    args, used, deadline if args.wait > 0 else None)
                # For a zero wait, allow the one immediate probe but never queue.
                if args.wait > 0 and time.monotonic() > deadline:
                    raise BusyError("overall admission deadline reached during resource probes")
                if cancel[0] is not None:
                    raise RunError("admission cancelled before command startup")
                claim = {"version": VERSION, "run_id": run_id, "nonce": nonce,
                         "host_id": config["host_id"], "boot_id": owner["boot_id"],
                         "owner": owner, "resources": resources, "cpus": cpus,
                         "gpus": args.gpus, "memory_mib": args.memory_mib,
                         "run_dir": str(args.run_dir), "kill_grace": args.kill_grace,
                         "created_utc": utc_now()}
                validate_claim(claim, config, run_id)
                atomic_json(path / "claims" / (run_id + ".json"), claim, config["file_mode"])
                return claim, {"cpu": cpu_probe, "gpu": gpu_probe,
                               "mem_available_bytes": available_bytes}
        except BusyError as exc:
            last_error = str(exc)
        if args.wait == 0 or time.monotonic() >= deadline:
            raise BusyError(last_error)
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def require_pidfds():
    if sys.platform != "linux" or not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise RunError("Linux pidfd support is required for verified cancellation; select a capable Python build")
    fd = os.pidfd_open(os.getpid())
    try:
        signal.pidfd_send_signal(fd, 0)
    finally:
        os.close(fd)


def enable_subreaper():
    require_pidfds()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "cannot enable child subreaper")
    flag = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(flag), 0, 0, 0) != 0 or flag.value != 1:
        raise RunError("child subreaper enforcement could not be verified")


def own_children(pid):
    children = set()
    task_dir = Path(f"/proc/{pid}/task")
    try:
        tasks = list(task_dir.iterdir())
    except FileNotFoundError:
        return children
    for task in tasks:
        try:
            value = (task / "children").read_text()
        except FileNotFoundError:
            continue
        fields = value.split()
        if not all(field.isdigit() for field in fields):
            raise RunError("malformed kernel descendant census")
        children.update(map(int, fields))
    return children


def descendants():
    result = {}
    todo = list(own_children(os.getpid()))
    seen = set()
    while todo:
        pid = todo.pop()
        if pid in seen:
            continue
        seen.add(pid)
        identity = rp.process_identity(pid)
        if identity is None:
            continue
        if identity["uid"] != os.geteuid():
            raise RunError("descendant ownership changed; keeping reservation")
        result[pid] = identity
        todo.extend(own_children(pid))
    return result


def parent_snapshot(pid):
    """Read one PID's start and real parent without whitespace-splitting comm."""
    try:
        value = Path(f"/proc/{pid}/stat").read_bytes()
    except FileNotFoundError:
        return None
    end = value.rfind(b")")
    first = value.find(b"(")
    fields = value[end + 1:].split() if end > first >= 0 else []
    try:
        if int(value[:first].strip()) != pid or len(fields) < 20:
            raise ValueError("invalid process stat")
        return {"pid": pid, "ppid": int(fields[1]), "start_ticks": int(fields[19])}
    except (ValueError, IndexError) as exc:
        raise RunError("cannot verify descendant parent identity") from exc


def ancestry_confirmed(identity):
    """Validate current parent/start relationships, not a stale children list.

    The caller holds a pidfd for the target. Every observed edge is read again
    after the chain reaches this still-live subreaper. A vanished/reused/reparented
    node means no signal; the next census can retry the newly adopted child.
    """
    chain = []
    seen = set()
    pid = identity["pid"]
    for _ in range(4096):
        if pid in seen or pid <= 0:
            return False
        seen.add(pid)
        node = parent_snapshot(pid)
        if node is None:
            return False
        if not chain and node["start_ticks"] != identity["start_ticks"]:
            return False
        chain.append(node)
        if node["ppid"] == os.getpid():
            break
        pid = node["ppid"]
    else:
        raise RunError("descendant ancestry exceeded its bound")
    for node in chain:
        if parent_snapshot(node["pid"]) != node:
            return False
    return True


def signal_identity(identity, number, *, require_descendant=False):
    if identity.get("boot_id") != rp.boot_id() or identity.get("uid") != os.geteuid():
        raise RunError("refusing to signal a process outside the current user's boot identity")
    try:
        fd = os.pidfd_open(identity["pid"])
    except ProcessLookupError:
        return False
    try:
        current = rp.process_identity(identity["pid"])
        if current is None:
            return False
        if not same_identity(identity, current):
            raise RunError("process identity changed before signaling")
        if require_descendant and not ancestry_confirmed(identity):
            return False
        try:
            signal.pidfd_send_signal(fd, number)
        except ProcessLookupError:
            return False
    finally:
        os.close(fd)
    return True


def reap_children(exits):
    """ECHILD after subreaper adoption is the kernel proof used for release."""
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return True
        if pid == 0:
            return False
        code = os.waitstatus_to_exitcode(status)
        exits.append({"pid": pid, "exit_code": code if code >= 0 else 128 - code})


def bootstrap(args):
    ready_fd, gate_fd = args.ready_fd, args.gate_fd
    try:
        os.sched_setaffinity(0, args.cpus)
        actual = sorted(os.sched_getaffinity(0))
        if actual != sorted(args.cpus):
            raise RunError("worker affinity differs from the requested CPU set")
        ready = {"ok": True, "pid": os.getpid(), "cpus": actual,
                 "thread_environment": {name: os.environ.get(name) for name in THREAD_VARIABLES}}
        os.write(ready_fd, (json.dumps(ready) + "\n").encode())
        os.close(ready_fd)
        ready_fd = -1
        permission = os.read(gate_fd, 1)
        os.close(gate_fd)
        gate_fd = -1
        if permission != b"G":
            return 126
        command = args.command
        if command[:1] == ["--"]:
            command = command[1:]
        os.execvpe(command[0], command, os.environ)
    except BaseException as exc:
        if ready_fd >= 0:
            with contextlib.suppress(OSError):
                os.write(ready_fd, (json.dumps({"ok": False, "error": str(exc)}) + "\n").encode())
        return 126
    finally:
        for fd in (ready_fd, gate_fd):
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)


def read_ready(fd, deadline, cancel):
    chunks = bytearray()
    while time.monotonic() < deadline:
        if cancel[0] is not None:
            raise RunError("cancelled before command startup")
        readable, _, _ = select.select([fd], [], [], min(0.05, max(0, deadline - time.monotonic())))
        if not readable:
            continue
        block = os.read(fd, 4096)
        if not block:
            break
        chunks.extend(block)
        if len(chunks) > 65536:
            raise RunError("worker readiness response exceeds its bound")
        if b"\n" in chunks:
            value = json.loads(chunks.decode())
            if not isinstance(value, dict) or not value.get("ok"):
                raise RunError("worker readiness failed: " + str(value))
            return value
    raise RunError("worker readiness did not complete before its deadline")


def verify_memory(args, pid):
    if not (args.require_memory_cap or args.require_no_swap):
        try:
            return rp.effective_memory_limits(pid)
        except rp.ProbeError as exc:
            return {"verified": False, "reason": str(exc)}
    limits = rp.effective_memory_limits(pid)
    memory = limits.get("memory_max")
    if args.require_memory_cap and (type(memory) is not int or memory > args.memory_mib * 1024 * 1024):
        raise RunError("the actual worker cgroup does not enforce the required memory cap")
    if args.require_no_swap and limits.get("swap_max") != 0:
        raise RunError("the actual worker cgroup does not enforce zero swap")
    return limits


def finish_claim(path, config, claim, terminal):
    if not terminal.get("quiescent"):
        raise RunError("cannot release a reservation without kernel quiescence proof")
    with admission_gate(path, time.monotonic() + 30):
        claim_path = path / "claims" / (claim["run_id"] + ".json")
        existing = validate_claim(read_json(claim_path), config, claim["run_id"])
        if existing["nonce"] != claim["nonce"] or not same_identity(existing["owner"], claim["owner"]):
            raise RunError("reservation identity changed; refusing release")
        summary = {key: terminal[key] for key in ("version", "run_id", "nonce", "host_id", "boot_id",
                                                  "owner", "quiescent", "state", "exit_code", "finished_utc")}
        summary.update({"allocation_present": False, "run_dir": claim["run_dir"],
                        "resources": claim["resources"], "memory_mib": claim["memory_mib"]})
        atomic_json(path / "finished" / (claim["run_id"] + ".json"), summary, config["file_mode"])
        claim_path.unlink()
        directory_sync(claim_path.parent)


def supervise(args, path, config, claim, admission, cancel):
    run_dir = args.run_dir
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    thread_env = {name: str(args.threads) for name in THREAD_VARIABLES}
    script = Path(__file__).resolve()
    record = {**claim, "state": "starting", "command": command,
              "helper_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
              "thread_environment": thread_env, "admission": admission,
              "time_limit_seconds": args.time_limit,
              "memory_accounting": "declared reservation; hard cap only if separately verified"}
    atomic_json(run_dir / "run.json", record)
    started = time.monotonic()
    deadline = started + args.time_limit
    exits = []
    primary_pid = None
    reason = None
    phase = "preflight_failed"
    signal_started = None
    signaled = {}
    quiescent = False
    ready_read = gate_write = None
    stdout = stderr = None
    try:
        stdout = (run_dir / "stdout.log").open("xb")
        stderr = (run_dir / "stderr.log").open("xb")
        ready_read, ready_write = os.pipe()
        gate_read, gate_write = os.pipe()
        environment = dict(os.environ)
        environment.update(thread_env)
        if args.gpus:
            environment["CUDA_VISIBLE_DEVICES"] = ",".join(
                admission["gpu"]["devices"][str(index)]["uuid"] for index in args.gpus)
        worker_args = [sys.executable, str(script), "_worker", "--ready-fd", str(ready_write),
                       "--gate-fd", str(gate_read), "--cpus", ",".join(map(str, claim["cpus"])), "--", *command]
        try:
            child = subprocess.Popen(worker_args, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                     env=environment, start_new_session=True,
                                     pass_fds=(ready_write, gate_read))
            primary_pid = child.pid
            # Reaping is deliberately owned by the subreaper loop, not Popen.
            child.returncode = 0
        finally:
            os.close(ready_write)
            os.close(gate_read)
        ready = read_ready(ready_read, min(deadline, started + 10), cancel)
        if ready.get("pid") != primary_pid or ready.get("cpus") != sorted(claim["cpus"]):
            raise RunError("worker readiness identity or affinity mismatch")
        if ready.get("thread_environment") != thread_env:
            raise RunError("worker native-thread environment was not applied")
        ready["identity"] = rp.process_identity(primary_pid)
        ready["memory_limits"] = verify_memory(args, primary_pid)
        if ready["identity"] is None:
            raise RunError("worker exited before required controls were verified")
        # Claims now exclude cooperating launches. Check external occupancy again
        # while the child is parked behind the execution gate.
        siblings = sorted({s for cpu in claim["cpus"] for s in rp.cpu_topology()[cpu]["siblings"]})
        post_cpu = cpu_snapshot(args, siblings, deadline)
        post_gpu = gpu_snapshot(args, deadline)
        if not post_cpu.get("idle") or not post_gpu.get("idle"):
            raise RunError("resources became busy after reservation; command was not started")
        if args.gpus and any(post_gpu["devices"][str(index)]["uuid"] != admission["gpu"]["devices"][str(index)]["uuid"]
                             for index in args.gpus):
            raise RunError("GPU index-to-UUID mapping changed before command startup")
        if cancel[0] is not None or time.monotonic() >= deadline:
            raise RunError("cancelled or timed out before command startup")
        ready["post_reservation"] = {"cpu": post_cpu, "gpu": post_gpu}
        atomic_json(run_dir / "ready.json", ready)
        record.update({"state": "running", "worker": ready["identity"], "started_utc": utc_now()})
        atomic_json(run_dir / "run.json", record)
        os.write(gate_write, b"G")
        os.close(gate_write)
        gate_write = None
        phase = "running"
    except BaseException as exc:
        reason = str(exc)
        if cancel[0] is not None:
            phase = "cancelled"
        elif time.monotonic() >= deadline:
            phase = "timed_out"
    finally:
        if ready_read is not None:
            with contextlib.suppress(OSError):
                os.close(ready_read)
        if gate_write is not None:
            with contextlib.suppress(OSError):
                os.close(gate_write)
        for stream in (stdout, stderr):
            if stream is not None:
                stream.close()
    try:
        while True:
            quiescent = reap_children(exits)
            if quiescent:
                break
            if cancel[0] is not None and reason is None:
                reason, phase = "received signal " + str(cancel[0]), "cancelled"
            if time.monotonic() >= deadline and reason is None:
                reason, phase = "time limit reached", "timed_out"
            if reason is None and any(item["exit_code"] != 0 for item in exits):
                reason, phase = "a workload process exited unsuccessfully", "failed"
            if reason is not None:
                if signal_started is None:
                    signal_started = time.monotonic()
                number = signal.SIGKILL if time.monotonic() - signal_started >= args.kill_grace else signal.SIGTERM
                for pid, identity in descendants().items():
                    token = (identity["pid"], identity["start_ticks"], number)
                    if token not in signaled:
                        if signal_identity(identity, number, require_descendant=True):
                            signaled[token] = True
                if time.monotonic() - signal_started > args.kill_grace + 10:
                    raise RunError("descendants did not quiesce after bounded cancellation; reservation retained")
            time.sleep(0.02)
    except BaseException as exc:
        reason = str(exc)
        phase = "supervision_failed"
    primary = next((item["exit_code"] for item in exits if item["pid"] == primary_pid), None)
    if phase == "running":
        phase = "completed" if primary == 0 and all(item["exit_code"] == 0 for item in exits) else "failed"
    if phase == "timed_out":
        exit_code = 124
    elif phase == "cancelled":
        exit_code = 128 + (cancel[0] or signal.SIGTERM)
    elif phase == "completed":
        exit_code = 0
    elif phase == "failed" and primary:
        exit_code = primary
    else:
        exit_code = 125
    terminal = {"version": VERSION, "run_id": claim["run_id"], "nonce": claim["nonce"],
                "host_id": claim["host_id"], "boot_id": claim["boot_id"], "owner": claim["owner"],
                "state": phase, "exit_code": exit_code, "primary_exit_code": primary,
                "child_exits": exits, "quiescent": quiescent, "reason": reason,
                "finished_utc": utc_now(), "allocation_present": True}
    atomic_json(run_dir / "terminal.json", terminal)
    if quiescent:
        finish_claim(path, config, claim, terminal)
        terminal["allocation_present"] = False
        atomic_json(run_dir / "terminal.json", terminal)
    emit({"ok": exit_code == 0, **terminal, "run_dir": str(run_dir)})
    return exit_code


def run_command(args):
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise RunError("a command after -- is required")
    if args.threads > (len(args.cpus) if args.cpus else args.cores):
        raise RunError("thread setting exceeds the number of selected logical CPUs")
    path, config = namespace(args.state_dir)
    enable_subreaper()
    owner = rp.process_identity(os.getpid())
    if owner is None or owner["uid"] != os.geteuid():
        raise RunError("cannot establish supervisor process identity")
    run_id = args.run_id or (datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:12])
    nonce = uuid.uuid4().hex
    if args.run_dir.exists() or args.run_dir.is_symlink():
        raise RunError("run directory already exists; evidence will not be overwritten")
    args.run_dir.mkdir(mode=0o700)
    args.run_dir = args.run_dir.resolve()
    cancel = [None]
    prior = {}
    for number in (signal.SIGTERM, signal.SIGINT):
        prior[number] = signal.signal(number, lambda n, frame: cancel.__setitem__(0, n))
    try:
        claim, admission = reserve(args, path, config, owner, run_id, nonce, cancel)
        return supervise(args, path, config, claim, admission, cancel)
    finally:
        for number, handler in prior.items():
            signal.signal(number, handler)


def claim_status(claim):
    try:
        alive = same_identity(claim["owner"], rp.process_identity(claim["owner"]["pid"]))
    except (rp.ProbeError, OSError):
        alive = None
    state = "active" if alive else "owner_dead_reservation_retained"
    if alive is None:
        state = "owner_unknown_reservation_retained"
    if claim["owner"]["uid"] == os.geteuid():
        try:
            local = read_json(Path(claim["run_dir"]) / "run.json")
            if alive and local.get("nonce") == claim["nonce"]:
                state = local.get("state", state)
        except (OSError, ValueError, RunError):
            pass
    return {**claim, "allocation_present": True, "supervisor_alive": alive, "state": state}


def status_command(args):
    path, config = namespace(args.state_dir)
    with admission_gate(path, time.monotonic() + 5):
        claims = claims_in(path, config)
        if args.run_id:
            selected = [item for item in claims if item["run_id"] == args.run_id]
            if not selected:
                finished = path / "finished" / (args.run_id + ".json")
                if not finished.exists():
                    raise RunError("run ID not found")
                emit({"ok": True, "runs": [read_json(finished)]})
                return 0
        else:
            selected = claims
        emit({"ok": True, "state_dir": str(path), "runs": [claim_status(item) for item in selected]})
    return 0


def get_claim(path, config, run_id):
    with admission_gate(path, time.monotonic() + 5):
        value = read_json(path / "claims" / (run_id + ".json"))
        return validate_claim(value, config, run_id)


def stop_command(args):
    require_pidfds()
    path, config = namespace(args.state_dir)
    try:
        claim = get_claim(path, config, args.run_id)
    except FileNotFoundError:
        finished = path / "finished" / (args.run_id + ".json")
        if finished.exists():
            emit({"ok": True, "already_finished": True, "runs": [read_json(finished)]})
            return 0
        raise RunError("run ID not found")
    if claim["owner"]["uid"] != os.geteuid():
        raise RunError("refusing to stop another user's run")
    current = rp.process_identity(claim["owner"]["pid"])
    if not same_identity(claim["owner"], current):
        raise RunError("recorded supervisor is absent or its PID was reused; reservation retained")
    signal_identity(claim["owner"], signal.SIGTERM)
    deadline = time.monotonic() + args.wait
    while True:
        receipt_path = path / "finished" / (args.run_id + ".json")
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if receipt.get("nonce") == claim["nonce"] and receipt.get("quiescent"):
                emit({"ok": True, "stopped": True, "runs": [receipt]})
                return 0
        if time.monotonic() >= deadline:
            emit({"ok": False, "stopped": False, "allocation_present": True,
                  "error": "stop not confirmed within the observation deadline", "run_id": args.run_id})
            return 3
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def recover_command(args):
    path, config = namespace(args.state_dir)
    with admission_gate(path, time.monotonic() + 5):
        claim_path = path / "claims" / (args.run_id + ".json")
        claim = validate_claim(read_json(claim_path), config, args.run_id)
        if claim["owner"]["uid"] != os.geteuid() and config["uid"] != os.geteuid():
            raise RunError("only the run owner or namespace owner may recover its claim")
        current_boot = rp.boot_id()
        proof = "different_boot" if claim["boot_id"] != current_boot else None
        if proof is None:
            if same_identity(claim["owner"], rp.process_identity(claim["owner"]["pid"])):
                raise RunError("supervisor is still alive; recovery refused")
            try:
                terminal = read_json(Path(claim["run_dir"]) / "terminal.json")
            except (OSError, ValueError, RunError) as exc:
                raise RunError("same-boot dead owner has no valid quiescence proof; reservation retained") from exc
            if (terminal.get("version") != VERSION
                    or terminal.get("boot_id") != claim["boot_id"]
                    or terminal.get("state") not in {"completed", "failed", "cancelled", "timed_out", "preflight_failed", "supervision_failed"}
                    or type(terminal.get("exit_code")) is not int
                    or not isinstance(terminal.get("finished_utc"), str)
                    or terminal.get("quiescent") is not True or terminal.get("nonce") != claim["nonce"]
                    or terminal.get("run_id") != args.run_id or terminal.get("host_id") != config["host_id"]
                    or not same_identity(terminal.get("owner"), claim["owner"])):
                raise RunError("terminal receipt does not prove this reservation quiescent; reservation retained")
            proof = "matching_quiescent_terminal_receipt"
        summary = {"version": VERSION, "run_id": args.run_id, "nonce": claim["nonce"],
                   "host_id": claim["host_id"], "boot_id": claim["boot_id"], "owner": claim["owner"],
                   "state": "recovered", "quiescent": True, "allocation_present": False,
                   "proof": proof, "finished_utc": utc_now(), "run_dir": claim["run_dir"],
                   "resources": claim["resources"], "memory_mib": claim["memory_mib"]}
        atomic_json(path / "finished" / (args.run_id + ".json"), summary, config["file_mode"])
        claim_path.unlink()
        directory_sync(claim_path.parent)
    emit({"ok": True, "runs": [summary]})
    return 0


def probe_command(args):
    if not args.cpus and not args.gpus:
        raise RunError("probe requires --cpus and/or --gpus")
    result = {"ok": True, "reservation": False, "observed_utc": utc_now()}
    if args.cpus:
        topology = rp.cpu_topology()
        if not set(args.cpus) <= set(topology):
            raise RunError("requested CPU is offline or unknown")
        siblings = sorted({s for cpu in args.cpus for s in topology[cpu]["siblings"]})
        result["cpu"] = rp.probe_cpu_idle(siblings, interval=args.sample_seconds,
                                          max_busy_percent=args.max_cpu_busy)
    if args.gpus:
        result["gpu"] = gpu_snapshot(args)
    result["ok"] = all(item.get("idle") for name, item in result.items() if name in ("cpu", "gpu"))
    emit(result)
    return 0 if result["ok"] else 3


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="initialize a new explicit host-bound allocation namespace")
    init.add_argument("--state-dir", required=True, type=absolute_path)
    init.add_argument("--memory-budget-mib", required=True, type=positive_int)
    init.add_argument("--group")
    run = sub.add_parser("run", help="reserve resources and supervise a new command's complete descendant tree")
    run.add_argument("--state-dir", required=True, type=absolute_path)
    cpu = run.add_mutually_exclusive_group(required=True)
    cpu.add_argument("--cpus", type=cpu_list)
    cpu.add_argument("--cores", type=positive_int)
    run.add_argument("--memory-mib", required=True, type=positive_int)
    run.add_argument("--time-limit", required=True, type=positive)
    run.add_argument("--run-dir", required=True, type=absolute_path)
    run.add_argument("--run-id", type=id_value)
    run.add_argument("--threads", type=positive_int, default=1)
    run.add_argument("--wait", type=nonnegative, default=0)
    run.add_argument("--kill-grace", type=nonnegative, default=5)
    run.add_argument("--require-memory-cap", action="store_true")
    run.add_argument("--require-no-swap", action="store_true")
    run.add_argument("command", nargs=argparse.REMAINDER)
    probe = sub.add_parser("probe", help="observe current occupancy without reserving resources")
    probe.add_argument("--cpus", type=cpu_list)
    for item in (run, probe):
        item.add_argument("--gpus", type=cpu_list, default=[])
        item.add_argument("--sample-seconds", type=positive, default=.25)
        item.add_argument("--max-cpu-busy", type=percentage, default=5)
        item.add_argument("--max-gpu-util", type=percentage, default=5)
        item.add_argument("--max-gpu-memory-mib", type=nonnegative, default=0)
    for name in ("status", "stop", "recover"):
        item = sub.add_parser(name)
        item.add_argument("--state-dir", required=True, type=absolute_path)
        item.add_argument("--run-id", required=name != "status", type=id_value)
        if name == "stop":
            item.add_argument("--wait", type=nonnegative, default=30)
    worker = sub.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("--ready-fd", type=int, required=True)
    worker.add_argument("--gate-fd", type=int, required=True)
    worker.add_argument("--cpus", type=cpu_list, required=True)
    worker.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    if sys.version_info < (3, 9):
        emit({"ok": False, "error": "Python 3.9 or newer is required", "kind": "unsupported_interpreter"})
        return 2
    try:
        args = make_parser().parse_args(argv)
        actions = {"init": init_namespace, "run": run_command, "status": status_command,
                   "stop": stop_command, "recover": recover_command, "probe": probe_command,
                   "_worker": bootstrap}
        return actions[args.action](args)
    except SystemExit as exc:
        return int(exc.code)
    except BusyError as exc:
        emit({"ok": False, "error": str(exc), "kind": "busy"})
        return 3
    except (RunError, rp.ProbeError, OSError, ValueError, KeyError) as exc:
        emit({"ok": False, "error": str(exc), "kind": "unknown_or_invalid"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
