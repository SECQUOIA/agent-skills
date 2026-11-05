#!/usr/bin/env python3
"""Fail-closed Linux resource observations for remote_run.py.

These functions observe state; they do not reserve a resource. The caller must
perform admission using its common namespace before relying on an observation.
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import uuid


class ProbeError(RuntimeError):
    """Required state could not be established reliably."""


PROC_ROOT = Path("/proc")
CPU_ROOT = Path("/sys/devices/system/cpu")
MACHINE_ID_PATHS = (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id"))
GPU_QUERY_TIMEOUT = 10


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ProbeError(f"Cannot read required state at {path}: {exc}") from exc


def _integer(value: str, label: str, *, minimum: int = 0) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) < minimum:
        raise ProbeError(f"Invalid {label}: {value!r}")
    return int(value)


def parse_cpu_list(value: str) -> list[int]:
    """Parse Linux CPU-list syntax, rejecting malformed or duplicate entries."""
    result: list[int] = []
    if not value:
        raise ProbeError("CPU list is empty")
    for part in value.split(","):
        if re.fullmatch(r"[0-9]+", part):
            values = [_integer(part, "CPU ID")]
        elif re.fullmatch(r"[0-9]+-[0-9]+", part):
            lo, hi = map(int, part.split("-"))
            if hi < lo or hi - lo > 1_000_000:
                raise ProbeError(f"Invalid CPU range: {part!r}")
            values = range(lo, hi + 1)
        else:
            raise ProbeError(f"Invalid CPU-list segment: {part!r}")
        result.extend(values)
    if len(result) != len(set(result)):
        raise ProbeError("CPU list contains duplicates")
    return sorted(result)


def _ids(values: list[int], label: str, *, allow_empty: bool = False) -> list[int]:
    result = list(values)
    if (not result and not allow_empty) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in result
    ):
        raise ProbeError(f"{label} must contain nonnegative integer IDs")
    if len(result) != len(set(result)):
        raise ProbeError(f"{label} contains duplicate IDs")
    return result


def _number(value: str | float, label: str, *, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProbeError(f"Invalid {label}: {value!r}") from exc
    if not math.isfinite(number) or number < 0 or (
        maximum is not None and number > maximum
    ):
        raise ProbeError(f"Invalid {label}: {value!r}")
    return number


def host_id() -> str:
    for path in MACHINE_ID_PATHS:
        try:
            value = _read(path)
        except ProbeError:
            continue
        if re.fullmatch(r"[0-9a-fA-F]{32}", value) and int(value, 16):
            return hashlib.sha256(value.lower().encode("ascii")).hexdigest()
    raise ProbeError("No valid stable machine ID is available")


def boot_id() -> str:
    value = _read(PROC_ROOT / "sys/kernel/random/boot_id")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ProbeError("Malformed Linux boot ID") from exc
    if str(parsed) != value.lower() or parsed.int == 0:
        raise ProbeError("Malformed Linux boot ID")
    return str(parsed)


def _start_ticks(stat: str, pid: int) -> int:
    # comm is parenthesized and can itself contain whitespace and parentheses.
    # The fields following its final ')' begin at documented field 3 (state).
    end = stat.rfind(")")
    if not stat.startswith(f"{pid} (") or end < 0:
        raise ProbeError(f"Malformed process stat for PID {pid}")
    fields = stat[end + 1:].split()
    if len(fields) < 20 or not re.fullmatch(r"[A-Za-z]", fields[0]):
        raise ProbeError(f"Malformed process stat for PID {pid}")
    return _integer(fields[19], "process start ticks")


def process_identity(pid: int) -> dict | None:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ProbeError("PID must be a positive integer")
    directory = PROC_ROOT / str(pid)
    try:
        # Linux comm is arbitrary bytes, not guaranteed UTF-8 or ASCII. Latin-1
        # preserves each byte; only the ASCII state/start-time tail is parsed.
        before = (directory / "stat").read_text(encoding="latin-1").strip()
        owner = directory.stat().st_uid
        after = (directory / "stat").read_text(encoding="latin-1").strip()
    except FileNotFoundError as exc:
        try:
            directory.stat()
        except FileNotFoundError:
            return None
        except OSError as stat_exc:
            raise ProbeError(f"Cannot establish existence of PID {pid}") from stat_exc
        raise ProbeError(f"Incomplete process state for PID {pid}") from exc
    except (OSError, UnicodeError) as exc:
        raise ProbeError(f"Cannot identify PID {pid}: {exc}") from exc
    start = _start_ticks(before, pid)
    if start != _start_ticks(after, pid):
        raise ProbeError(f"PID {pid} changed while identifying it")
    return {"pid": pid, "start_ticks": start, "boot_id": boot_id(), "uid": owner}


def cpu_topology() -> dict[int, dict]:
    online = set(parse_cpu_list(_read(CPU_ROOT / "online")))
    topology: dict[int, dict] = {}
    for cpu in sorted(online):
        directory = CPU_ROOT / f"cpu{cpu}/topology"
        socket = _integer(_read(directory / "physical_package_id"), "socket ID")
        core = _integer(_read(directory / "core_id"), "physical core ID")
        siblings = set(parse_cpu_list(_read(directory / "thread_siblings_list")))
        if cpu not in siblings:
            raise ProbeError(f"CPU {cpu} is absent from its own sibling list")
        topology[cpu] = {
            "resource_id": f"cpu:{socket}:{core}",
            "siblings": sorted(siblings & online),
        }
    for cpu, data in topology.items():
        expected = {
            other for other, item in topology.items()
            if item["resource_id"] == data["resource_id"]
        }
        if set(data["siblings"]) != expected:
            raise ProbeError(f"Inconsistent physical-core sibling mapping for CPU {cpu}")
    return topology


def _cpu_times(cpus: list[int]) -> dict[int, tuple[int, int]]:
    wanted = set(cpus)
    result: dict[int, tuple[int, int]] = {}
    for line in _read(PROC_ROOT / "stat").splitlines():
        fields = line.split()
        if not fields or not re.fullmatch(r"cpu[0-9]+", fields[0]):
            continue
        cpu = int(fields[0][3:])
        if cpu not in wanted:
            continue
        if cpu in result or len(fields) < 9:
            raise ProbeError(f"Missing or duplicate CPU-time counters for CPU {cpu}")
        counters = [_integer(value, "CPU-time counter") for value in fields[1:9]]
        # guest/guest_nice are already included in user/nice. Treat iowait and
        # steal conservatively as non-idle, rather than concealing pressure.
        result[cpu] = (sum(counters), counters[3])
    if set(result) != wanted:
        raise ProbeError("CPU-time counters are unavailable for requested CPUs")
    return result


def probe_cpu_idle(
    cpus: list[int], interval: float = .25, max_busy_percent: float = 5.0,
) -> dict:
    cpus = _ids(cpus, "CPU request")
    interval = _number(interval, "sample interval")
    threshold = _number(max_busy_percent, "CPU busy threshold", maximum=100)
    if interval <= 0:
        raise ProbeError("Sample interval must be positive")
    before = _cpu_times(cpus)
    time.sleep(interval)
    after = _cpu_times(cpus)
    busy = {}
    for cpu in cpus:
        total = after[cpu][0] - before[cpu][0]
        idle = after[cpu][1] - before[cpu][1]
        if total <= 0 or idle < 0 or idle > total:
            raise ProbeError(f"Invalid sampled CPU-time delta for CPU {cpu}")
        busy[str(cpu)] = 100.0 * (total - idle) / total
    return {"idle": all(value <= threshold for value in busy.values()), "busy_percent": busy}


def _positive_timeout(timeout: float) -> float:
    value = _number(timeout, "GPU query timeout")
    if value <= 0:
        raise ProbeError("GPU query timeout must be positive")
    return value


def _remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise ProbeError("GPU probe deadline expired")
    return value


def _nvidia_query(fields: str, timeout: float = GPU_QUERY_TIMEOUT) -> list[list[str]]:
    kind = "gpu" if fields.startswith("index,") else "compute-apps"
    command = ["nvidia-smi", f"--query-{kind}={fields}", "--format=csv,noheader,nounits"]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=_positive_timeout(timeout),
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ProbeError(f"GPU driver query failed: {exc}") from exc
    if result.returncode != 0 or result.stderr.strip():
        raise ProbeError(f"GPU driver query failed (exit {result.returncode})")
    try:
        return [
            [cell.strip() for cell in row]
            for row in csv.reader(result.stdout.splitlines(), strict=True)
            if row
        ]
    except csv.Error as exc:
        raise ProbeError("Malformed GPU driver CSV response") from exc


def _gpu_uuid(value: str) -> str:
    if not re.fullmatch(
        r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value,
    ):
        raise ProbeError(f"Invalid physical GPU UUID: {value!r}")
    return "GPU-" + value[4:].lower()


def gpu_inventory(timeout: float = GPU_QUERY_TIMEOUT) -> dict[int, dict]:
    rows = _nvidia_query("index,uuid,utilization.gpu,memory.used", timeout=timeout)
    if not rows:
        raise ProbeError("GPU driver returned no device inventory")
    devices = {}
    seen_uuids = set()
    for row in rows:
        if len(row) != 4:
            raise ProbeError("Malformed GPU inventory row")
        index = _integer(row[0], "GPU index")
        device_uuid = _gpu_uuid(row[1])
        if index in devices or device_uuid in seen_uuids:
            raise ProbeError("Duplicate GPU index or UUID in driver inventory")
        seen_uuids.add(device_uuid)
        devices[index] = {
            "uuid": device_uuid,
            "utilization": _number(row[2], "GPU utilization", maximum=100),
            "memory_mib": _number(row[3], "GPU memory use"),
        }
    return devices


def probe_gpu_idle(
    indices: list[int], max_util_percent: float = 5.0, max_memory_mib: float = 0.0,
    timeout: float = GPU_QUERY_TIMEOUT,
) -> dict:
    indices = _ids(indices, "GPU request", allow_empty=True)
    util_max = _number(max_util_percent, "GPU utilization threshold", maximum=100)
    memory_max = _number(max_memory_mib, "GPU memory threshold")
    if not indices:
        return {"idle": True, "devices": {}}
    deadline = time.monotonic() + _positive_timeout(timeout)
    inventory = gpu_inventory(timeout=_remaining(deadline))
    if not set(indices) <= inventory.keys():
        raise ProbeError("Requested GPU is absent from validated driver inventory")
    uuids = {data["uuid"]: index for index, data in inventory.items()}
    processes: dict[int, set[int]] = {index: set() for index in inventory}
    for row in _nvidia_query("gpu_uuid,pid", timeout=_remaining(deadline)):
        if len(row) != 2:
            raise ProbeError("Malformed GPU process row")
        device_uuid = _gpu_uuid(row[0])
        if device_uuid not in uuids:
            raise ProbeError("GPU process UUID is absent from validated inventory")
        pid = _integer(row[1], "GPU process PID", minimum=1)
        device = uuids[device_uuid]
        if pid in processes[device]:
            raise ProbeError("Duplicate GPU process row")
        processes[device].add(pid)
    selected = {
        str(index): {**inventory[index], "pids": sorted(processes[index])}
        for index in indices
    }
    idle = all(
        not data["pids"] and data["utilization"] <= util_max
        and data["memory_mib"] <= memory_max for data in selected.values()
    )
    return {"idle": idle, "devices": selected}


def _unescape_mount(value: str) -> str:
    return re.sub(r"\\(040|011|012|134)", lambda match: chr(int(match[1], 8)), value)


def _cgroup_path(pid: int) -> tuple[Path, Path]:
    unified = []
    for line in _read(PROC_ROOT / str(pid) / "cgroup").splitlines():
        fields = line.split(":", 2)
        if len(fields) != 3:
            raise ProbeError("Malformed process cgroup membership")
        if fields[0] == "0" and fields[1] == "":
            unified.append(fields[2])
    if len(unified) != 1:
        raise ProbeError("A single cgroup v2 membership is required")
    group = PurePosixPath(unified[0])
    if not group.is_absolute() or ".." in group.parts:
        raise ProbeError("Unresolvable process cgroup v2 path")
    mounts = []
    for line in _read(PROC_ROOT / "self/mountinfo").splitlines():
        before, separator, after = line.partition(" - ")
        if not separator or not after.startswith("cgroup2 "):
            continue
        fields = before.split()
        if len(fields) < 6:
            raise ProbeError("Malformed cgroup v2 mount record")
        root = PurePosixPath(_unescape_mount(fields[3]))
        mount = Path(_unescape_mount(fields[4]))
        if not root.is_absolute() or not mount.is_absolute() or ".." in root.parts:
            raise ProbeError("Malformed cgroup v2 mount path")
        try:
            relative = group.relative_to(root)
        except ValueError:
            continue
        try:
            base = mount.resolve(strict=True)
            target = (base / str(relative)).resolve(strict=True)
        except OSError as exc:
            raise ProbeError("Cannot resolve process cgroup directory") from exc
        if not target.is_relative_to(base):
            raise ProbeError("Process cgroup path leaves the cgroup mount")
        mounts.append((len(root.parts), base, target))
    if not mounts:
        raise ProbeError("No accessible cgroup v2 mount covers the worker")
    _, base, target = max(mounts, key=lambda item: item[0])
    return base, target


def _limit(value: str) -> int | None:
    return None if value == "max" else _integer(value, "cgroup hard limit")


def effective_memory_limits(pid: int) -> dict:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ProbeError("PID must be a positive integer")
    base, target = _cgroup_path(pid)
    memory = []
    swap = []
    cpus = None
    path = target
    while True:
        for name, values in (("memory.max", memory), ("memory.swap.max", swap)):
            file = path / name
            try:
                value = file.read_text(encoding="ascii").strip()
            except FileNotFoundError:
                continue
            except (OSError, UnicodeError) as exc:
                raise ProbeError(f"Cannot read effective cgroup limit {file}") from exc
            values.append(_limit(value))
        if cpus is None:
            file = path / "cpuset.cpus.effective"
            try:
                value = file.read_text(encoding="ascii").strip()
            except FileNotFoundError:
                pass
            except (OSError, UnicodeError) as exc:
                raise ProbeError(f"Cannot read effective CPU set {file}") from exc
            else:
                cpus = parse_cpu_list(value)
        if path == base:
            break
        path = path.parent
    if not memory or not swap or cpus is None:
        raise ProbeError("Required cgroup v2 memory/swap/CPU controls are unavailable")
    finite_memory = [value for value in memory if value is not None]
    finite_swap = [value for value in swap if value is not None]
    return {
        "memory_max": min(finite_memory) if finite_memory else None,
        "swap_max": min(finite_swap) if finite_swap else None,
        "cgroup": str(target),
        "cpus_effective": cpus,
    }
