"""Exercise real admission/supervision behavior with deterministic resource probes.

These tests fork the public CLI, pin tiny Python children to CPUs permitted by
the test host, and replace only host-capacity probes. They never need a GPU,
an SSH server, a solver, or an otherwise idle machine.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/remote-runs/scripts"
LINUX_RUNTIME = (
    sys.platform == "linux"
    and hasattr(os, "fork")
    and hasattr(os, "sched_getaffinity")
    and hasattr(os, "pidfd_open")
    and hasattr(signal, "pidfd_send_signal")
)


def load_runner():
    """Import the same script used by callers without running its CLI guard."""
    script = SCRIPTS / "remote_run.py"
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("test_remote_run_cli", script)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        import resource_probe

        return module, resource_probe
    finally:
        sys.path.pop(0)


def identity(pid):
    """Independent, name-aware identity reader for cleaning up test-owned PIDs."""
    try:
        text = Path(f"/proc/{pid}/stat").read_bytes()
        fields = text[text.rindex(b")") + 2 :].split()
        return (pid, int(fields[19]), Path(f"/proc/{pid}").stat().st_uid,
                fields[0].decode("ascii"))
    except (FileNotFoundError, ProcessLookupError):
        return None


def signal_owned(expected, sig):
    if expected is None:
        return
    pid, ticks, uid, _ = expected
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        live = identity(pid)
        if live is not None and live[:3] == (pid, ticks, uid):
            signal.pidfd_send_signal(fd, sig)
    except ProcessLookupError:
        pass
    finally:
        os.close(fd)


class Invocation:
    def __init__(self, pid, stdout, stderr):
        self.pid = pid
        self.stdout_path = stdout
        self.stderr_path = stderr
        self.returncode = None
        self.identity = identity(pid)

    def poll(self):
        if self.returncode is None:
            try:
                found, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                found, status = self.pid, 0
            if found:
                self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, timeout=8):
        deadline = time.monotonic() + timeout
        while self.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if self.returncode is None:
            raise AssertionError(
                f"CLI PID {self.pid} did not exit: {self.stderr_path.read_text()}"
            )
        return self.returncode

    @property
    def stdout(self):
        return self.stdout_path.read_text()

    @property
    def stderr(self):
        return self.stderr_path.read_text()

    def json(self):
        objects = []
        for line in self.stdout.splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                objects.append(value)
        if not objects:
            raise AssertionError(f"No JSON response: {self.stdout}\n{self.stderr}")
        return objects[-1]


@unittest.skipUnless(LINUX_RUNTIME, "requires Linux affinity, fork and pidfds")
class RemoteRunsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner, cls.probes = load_runner()
        cls.allowed = sorted(os.sched_getaffinity(0))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="secquoia-run-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.invocations = []
        self.payloads = []
        self.serial = 0
        self.addCleanup(self.cleanup_processes)
        self.init_namespace()

    def cleanup_processes(self):
        # Every signal is restricted to a recorded test-owned process identity.
        for call in self.invocations:
            if call.poll() is None:
                signal_owned(call.identity, signal.SIGTERM)
        deadline = time.monotonic() + 2
        while any(call.poll() is None for call in self.invocations):
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        for call in self.invocations:
            if call.poll() is None:
                signal_owned(call.identity, signal.SIGKILL)
                call.wait(3)
        for expected in self.payloads:
            signal_owned(expected, signal.SIGKILL)

    def spawn(self, args, *, smt_alias=False, probe_mode="idle", limits=None,
              fake_boot=None, memory_probe_marker=None, stale_census_pid=None):
        self.serial += 1
        stdout = self.root / f"cli-{self.serial}.out"
        stderr = self.root / f"cli-{self.serial}.err"
        stdout.touch()
        stderr.touch()
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            code = 99
            try:
                for target, file in [(1, stdout), (2, stderr)]:
                    fd = os.open(file, os.O_WRONLY | os.O_TRUNC)
                    os.dup2(fd, target)
                    os.close(fd)
                topology = {
                    cpu: {
                        "resource_id": f"cpu:0:{0 if smt_alias else index}",
                        "siblings": list(self.allowed) if smt_alias else [cpu],
                    }
                    for index, cpu in enumerate(self.allowed)
                }
                self.probes.cpu_topology = lambda: topology

                def cpu_probe(cpus, interval=.25, max_busy_percent=5):
                    if probe_mode == "unknown":
                        raise self.probes.ProbeError("synthetic unavailable CPU sample")
                    return {
                        "idle": probe_mode != "busy",
                        "busy_percent": {str(cpu): 99.0 if probe_mode == "busy" else 0.0
                                         for cpu in cpus},
                    }

                def gpu_probe(indices, max_util_percent=5, max_memory_mib=0, timeout=10):
                    if probe_mode == "gpu-unknown":
                        raise self.probes.ProbeError("synthetic driver failure")
                    return {
                        "idle": probe_mode != "gpu-busy",
                        "devices": {
                            str(index): {
                                "uuid": f"GPU-{index:08d}-0000-0000-0000-000000000000",
                                "utilization": 99 if probe_mode == "gpu-busy" else 0,
                                "memory_mib": 0,
                                "pids": [],
                            }
                            for index in indices
                        },
                    }

                self.probes.probe_cpu_idle = cpu_probe
                self.probes.gpu_inventory = lambda: {
                    index: {"uuid": f"GPU-{index:08d}-0000-0000-0000-000000000000",
                            "utilization": 0, "memory_mib": 0}
                    for index in range(3)
                }
                self.probes.probe_gpu_idle = gpu_probe
                if stale_census_pid is not None:
                    self.runner.own_children = lambda pid: (
                        {stale_census_pid} if pid == os.getpid() else set()
                    )
                if fake_boot is not None:
                    self.probes.boot_id = lambda: fake_boot
                if limits is not None:
                    def memory_probe(worker_pid):
                        if memory_probe_marker is not None:
                            memory_probe_marker.write_text(json.dumps({
                                "pid": worker_pid,
                                "affinity": sorted(os.sched_getaffinity(worker_pid)),
                            }))
                        if limits == "unknown":
                            raise self.probes.ProbeError("synthetic unavailable cgroup")
                        return limits

                    self.probes.effective_memory_limits = memory_probe
                try:
                    result = self.runner.main(args)
                    code = int(result or 0)
                except SystemExit as exc:
                    code = int(exc.code or 0) if isinstance(exc.code, (int, type(None))) else 1
            except BaseException:
                traceback.print_exc()
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(code)
        call = Invocation(pid, stdout, stderr)
        self.invocations.append(call)
        return call

    def call(self, args, **options):
        call = self.spawn(args, **options)
        call.wait()
        return call

    def init_namespace(self, budget=10):
        call = self.call([
            "init", "--state-dir", str(self.state),
            "--memory-budget-mib", str(budget),
        ])
        self.assertEqual(call.returncode, 0, call.stdout + call.stderr)

    def run_job(self, run_id, code, *, cpu=None, memory=2, options=(), **mocks):
        cpu = self.allowed[0] if cpu is None else cpu
        args = [
            "run", "--state-dir", str(self.state), "--cpus", str(cpu),
            "--memory-mib", str(memory), "--time-limit", "8",
            "--kill-grace", "0.1", "--run-dir", str(self.root / run_id),
            "--run-id", run_id,
        ]
        args.extend(options)
        args.extend(["--", sys.executable, "-c", code])
        return self.spawn(args, **mocks)

    def wait_path(self, path, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists() and path.stat().st_size:
                return
            time.sleep(0.01)
        diagnostics = "\n".join(call.stdout + call.stderr for call in self.invocations)
        self.fail(f"Timed out waiting for {path}:\n{diagnostics}")

    def remember_payload(self, marker):
        self.wait_path(marker)
        pid = int(marker.read_text())
        observed = identity(pid)
        self.assertIsNotNone(observed, f"payload {pid} exited before the handshake")
        self.payloads.append(observed)
        return observed

    def sleeper(self, marker, seconds=20, ignore_term=False):
        return (
            "import os, signal, time; from pathlib import Path; "
            + ("signal.signal(signal.SIGTERM, signal.SIG_IGN); " if ignore_term else "")
            + f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep({seconds})"
        )

    def stop(self, run_id):
        return self.call([
            "stop", "--state-dir", str(self.state), "--run-id", run_id,
            "--wait", "5",
        ])

    def claim(self, run_id):
        return self.state / "claims" / f"{run_id}.json"

    def terminal(self, run_id):
        return json.loads((self.root / run_id / "terminal.json").read_text())

    def test_two_concurrent_claimants_execute_only_one_command(self):
        markers = [self.root / "first.pid", self.root / "second.pid"]
        runs = [self.run_job(name, self.sleeper(marker))
                for name, marker in zip(["first", "second"], markers)]
        deadline = time.monotonic() + 4
        while not any(path.exists() for path in markers) and time.monotonic() < deadline:
            time.sleep(0.01)
        selected = [i for i, path in enumerate(markers) if path.exists()]
        self.assertEqual(len(selected), 1)
        winner = selected[0]
        self.remember_payload(markers[winner])
        loser = runs[1 - winner]
        self.assertNotEqual(loser.wait(), 0, loser.stdout + loser.stderr)
        self.assertFalse(markers[1 - winner].exists())
        self.assertEqual(len(list((self.state / "claims").glob("*.json"))), 1)
        self.assertEqual(self.stop(["first", "second"][winner]).returncode, 0)
        runs[winner].wait()

    def test_smt_aliases_are_one_reservation_resource(self):
        if len(self.allowed) < 2:
            self.skipTest("needs two allowed logical CPUs")
        marker = self.root / "smt-owner.pid"
        owner = self.run_job("smt-owner", self.sleeper(marker), smt_alias=True)
        self.remember_payload(marker)
        denied_marker = self.root / "smt-denied.pid"
        denied = self.run_job("smt-denied", self.sleeper(denied_marker),
                          cpu=self.allowed[1], smt_alias=True)
        self.assertNotEqual(denied.wait(), 0)
        self.assertFalse(denied_marker.exists())
        self.assertEqual(self.stop("smt-owner").returncode, 0)
        owner.wait()

    def test_memory_requests_are_accounted_atomically_across_distinct_cores(self):
        if len(self.allowed) < 2:
            self.skipTest("needs two allowed logical CPUs")
        a_marker, b_marker = self.root / "memory-a.pid", self.root / "memory-b.pid"
        first = self.run_job("memory-a", self.sleeper(a_marker), memory=8)
        self.remember_payload(a_marker)
        denied = self.run_job("memory-denied", "raise SystemExit(0)",
                          cpu=self.allowed[1], memory=3)
        self.assertNotEqual(denied.wait(), 0)
        self.assertFalse(self.claim("memory-denied").exists())
        second = self.run_job("memory-b", self.sleeper(b_marker),
                          cpu=self.allowed[1], memory=2)
        self.remember_payload(b_marker)
        self.assertEqual(self.stop("memory-a").returncode, 0)
        self.assertEqual(self.stop("memory-b").returncode, 0)
        first.wait()
        second.wait()

    def test_failed_gpu_claim_does_not_partially_reserve_a_cpu(self):
        if len(self.allowed) < 2:
            self.skipTest("needs two allowed logical CPUs")
        marker_a, marker_b = self.root / "gpu-a.pid", self.root / "gpu-b.pid"
        owner = self.run_job("gpu-a", self.sleeper(marker_a), options=["--gpus", "0"])
        self.remember_payload(marker_a)
        denied = self.run_job("gpu-denied", "raise SystemExit(0)",
                          cpu=self.allowed[1], options=["--gpus", "0"])
        self.assertNotEqual(denied.wait(), 0)
        self.assertFalse(self.claim("gpu-denied").exists())
        other = self.run_job("gpu-b", self.sleeper(marker_b), cpu=self.allowed[1],
                         options=["--gpus", "1"])
        self.remember_payload(marker_b)
        self.assertEqual(self.stop("gpu-a").returncode, 0)
        self.assertEqual(self.stop("gpu-b").returncode, 0)
        owner.wait()
        other.wait()

    def test_wait_has_one_bounded_deadline_and_no_partial_allocation(self):
        if len(self.allowed) < 2:
            self.skipTest("needs two allowed logical CPUs")
        marker = self.root / "wait-owner.pid"
        owner = self.run_job("wait-owner", self.sleeper(marker), options=["--gpus", "0,1"])
        self.remember_payload(marker)
        before = time.monotonic()
        waiting = self.run_job("wait-denied", "raise SystemExit(0)", cpu=self.allowed[1],
                           options=["--gpus", "0,1", "--wait", "0.2"])
        self.assertNotEqual(waiting.wait(3), 0)
        self.assertLess(time.monotonic() - before, 1.5)
        self.assertFalse(self.claim("wait-denied").exists())
        self.assertEqual(self.stop("wait-owner").returncode, 0)
        owner.wait()

    def test_term_interrupts_admission_gate_wait_without_unlock_or_user_command(self):
        gate = self.state / "admission.lock"
        held_marker = self.root / "held-gate.pid"
        code = (
            "import fcntl, os, time; from pathlib import Path; "
            f"lock = open({str(gate)!r}, 'r+'); "
            "fcntl.flock(lock.fileno(), fcntl.LOCK_EX); "
            f"Path({str(held_marker)!r}).write_text(str(os.getpid())); time.sleep(20)"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", code], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        holder_identity = self.remember_payload(held_marker)

        def reap_holder():
            signal_owned(holder_identity, signal.SIGKILL)
            holder.wait(timeout=3)

        self.addCleanup(reap_holder)
        marker = self.root / "waiting-command.pid"
        owner = self.run_job("gate-wait", self.sleeper(marker), options=["--wait", "600"])
        # Observing the supervisor's real open gate descriptor establishes that
        # the TERM handler is installed and admission is waiting on this lock.
        deadline = time.monotonic() + 4
        gate_open = False
        while owner.poll() is None and time.monotonic() < deadline:
            try:
                gate_open = any(fd.resolve() == gate
                                for fd in Path(f"/proc/{owner.pid}/fd").iterdir())
            except FileNotFoundError:
                gate_open = False
            if gate_open:
                break
            time.sleep(.01)
        self.assertTrue(gate_open, owner.stdout + owner.stderr)
        before = time.monotonic()
        signal_owned(owner.identity, signal.SIGTERM)
        self.assertNotEqual(owner.wait(2), 0)
        self.assertLess(time.monotonic() - before, 1.5)
        self.assertIsNone(holder.poll(), "admission lock was released to finish cancellation")
        self.assertFalse(marker.exists())
        self.assertFalse(self.claim("gate-wait").exists())

    def test_busy_or_unknown_probe_never_executes_user_command(self):
        for mode in ["busy", "unknown", "gpu-busy", "gpu-unknown"]:
            with self.subTest(mode=mode):
                run_id = "probe-" + mode
                marker = self.root / (run_id + ".pid")
                call = self.run_job(run_id, self.sleeper(marker), probe_mode=mode,
                                options=["--gpus", "0"] if mode.startswith("gpu") else [])
                self.assertNotEqual(call.wait(), 0, call.stdout + call.stderr)
                self.assertFalse(marker.exists())
                self.assertFalse(self.claim(run_id).exists())

    def test_cpu_only_run_does_not_require_a_working_gpu_driver(self):
        marker = self.root / "cpu-only.txt"
        call = self.run_job("cpu-only", f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')",
                        probe_mode="gpu-unknown")
        self.assertEqual(call.wait(), 0, call.stdout + call.stderr)
        self.assertEqual(marker.read_text(), "ok")
        self.assertFalse(self.claim("cpu-only").exists())
        self.assertTrue(self.terminal("cpu-only")["quiescent"])

    def test_primary_exit_does_not_release_detached_descendant_reservation(self):
        marker = self.root / "detached.pid"
        child_code = self.sleeper(marker, seconds=.8)
        code = (
            "import subprocess, sys; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}], "
            "start_new_session=True, close_fds=True)"
        )
        owner = self.run_job("detached", code)
        self.remember_payload(marker)
        self.assertIsNone(owner.poll())
        self.assertTrue(self.claim("detached").exists())
        contender = self.run_job("detached-denied", "raise SystemExit(0)")
        self.assertNotEqual(contender.wait(), 0)
        self.assertEqual(owner.wait(), 0, owner.stdout + owner.stderr)
        self.assertFalse(self.claim("detached").exists())
        receipt = self.terminal("detached")
        self.assertTrue(receipt["quiescent"])
        self.assertEqual(receipt["primary_exit_code"], 0)

    def test_failed_detached_child_is_retained_even_when_primary_exits_zero(self):
        child_code = "import time; time.sleep(.1); raise SystemExit(7)"
        code = (
            "import subprocess, sys; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}], "
            "start_new_session=True, close_fds=True)"
        )
        owner = self.run_job("child-failure", code)
        self.assertNotEqual(owner.wait(), 0)
        receipt = self.terminal("child-failure")
        self.assertEqual(receipt["primary_exit_code"], 0)
        self.assertNotEqual(receipt["exit_code"], 0)
        self.assertTrue(receipt["quiescent"])
        self.assertFalse(self.claim("child-failure").exists())

    def test_sigkill_supervisor_retains_claim_and_recovery_requires_proof(self):
        marker = self.root / "orphan.pid"
        code = (
            "import subprocess, sys; "
            f"subprocess.Popen([sys.executable, '-c', {self.sleeper(marker)!r}], "
            "start_new_session=True, close_fds=True)"
        )
        owner = self.run_job("orphan", code)
        payload = self.remember_payload(marker)
        signal_owned(owner.identity, signal.SIGKILL)
        self.assertEqual(owner.wait(), -signal.SIGKILL)
        self.assertIsNotNone(identity(payload[0]))
        self.assertTrue(self.claim("orphan").exists())
        denied = self.run_job("orphan-denied", "raise SystemExit(0)")
        self.assertNotEqual(denied.wait(), 0)
        recovered = self.call(["recover", "--state-dir", str(self.state), "--run-id", "orphan"])
        self.assertNotEqual(recovered.returncode, 0)
        self.assertTrue(self.claim("orphan").exists())
        status = self.call(["status", "--state-dir", str(self.state), "--run-id", "orphan"])
        runs = status.json()["runs"]
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0]["allocation_present"])
        self.assertFalse(runs[0]["supervisor_alive"])
        # Even after the orphan is manually stopped, a same-boot dead owner
        # without a durable quiescent receipt is not automatically reclaimable.
        signal_owned(payload, signal.SIGKILL)
        recovered = self.call(["recover", "--state-dir", str(self.state), "--run-id", "orphan"])
        self.assertNotEqual(recovered.returncode, 0)
        self.assertTrue(self.claim("orphan").exists())

    def test_recovery_can_finish_release_after_a_matching_quiescent_receipt(self):
        marker = self.root / "recover-complete.pid"
        owner = self.run_job("recover-complete", self.sleeper(marker, seconds=.15))
        self.remember_payload(marker)
        original = self.claim("recover-complete").read_bytes()
        self.assertEqual(owner.wait(), 0)
        self.assertTrue(self.terminal("recover-complete")["quiescent"])
        # Recreate only this owned test's original claim to model an interrupted
        # release after the durable quiescent receipt was committed.
        self.claim("recover-complete").write_bytes(original)
        recovered = self.call([
            "recover", "--state-dir", str(self.state), "--run-id", "recover-complete",
        ])
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertFalse(self.claim("recover-complete").exists())

    def test_different_boot_allows_recovery_of_an_old_durable_reservation(self):
        marker = self.root / "old-boot.pid"
        owner = self.run_job("old-boot", self.sleeper(marker))
        payload = self.remember_payload(marker)
        signal_owned(owner.identity, signal.SIGKILL)
        owner.wait()
        signal_owned(payload, signal.SIGKILL)
        self.assertTrue(self.claim("old-boot").exists())
        # Only the test child sees a simulated boot change. No real host state
        # changes and no still-running test workload is declared quiescent.
        recovered = self.call([
            "recover", "--state-dir", str(self.state), "--run-id", "old-boot",
        ], fake_boot="00000000-0000-0000-0000-000000000001")
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertFalse(self.claim("old-boot").exists())

    def test_recovery_rejects_a_quiescent_receipt_with_the_wrong_nonce(self):
        marker = self.root / "recover-invalid.pid"
        owner = self.run_job("recover-invalid", self.sleeper(marker, seconds=.15))
        self.remember_payload(marker)
        original = self.claim("recover-invalid").read_bytes()
        self.assertEqual(owner.wait(), 0)
        self.claim("recover-invalid").write_bytes(original)
        terminal_path = self.root / "recover-invalid" / "terminal.json"
        receipt = json.loads(terminal_path.read_text())
        receipt["nonce"] = "wrong-recovery-proof"
        terminal_path.write_text(json.dumps(receipt))
        recovered = self.call([
            "recover", "--state-dir", str(self.state), "--run-id", "recover-invalid",
        ])
        self.assertNotEqual(recovered.returncode, 0)
        self.assertTrue(self.claim("recover-invalid").exists())

    def test_term_stops_verified_detached_workers_before_releasing_claim(self):
        marker = self.root / "cancel-worker.pid"
        code = (
            "import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', {self.sleeper(marker, ignore_term=True)!r}], "
            "start_new_session=True, close_fds=True); time.sleep(20)"
        )
        owner = self.run_job("cancel", code)
        payload = self.remember_payload(marker)
        stopped = self.stop("cancel")
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assertNotEqual(owner.wait(), 0)
        self.assertIsNone(identity(payload[0]))
        self.assertTrue(self.terminal("cancel")["quiescent"])
        self.assertFalse(self.claim("cancel").exists())

    def test_non_utf8_worker_name_can_be_cancelled_reaped_and_released(self):
        marker = self.root / "binary-name.pid"
        code = (
            "import ctypes; "
            "assert ctypes.CDLL(None).prctl(15, ctypes.c_char_p(b'worker-\\xff'), 0, 0, 0) == 0; "
            + self.sleeper(marker, ignore_term=True)
        )
        owner = self.run_job("binary-name", code)
        payload = self.remember_payload(marker)
        # Verify the fixture actually installed the arbitrary byte name before
        # asking the production cancellation path to parse its identity.
        self.assertIn(b"worker-\xff", Path(f"/proc/{payload[0]}/stat").read_bytes())
        stopped = self.stop("binary-name")
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assertNotEqual(owner.wait(), 0)
        self.assertIsNone(identity(payload[0]))
        self.assertTrue(self.terminal("binary-name")["quiescent"])
        self.assertFalse(self.claim("binary-name").exists())

    def test_time_limit_kills_term_ignoring_payload_and_releases_after_quiescence(self):
        marker = self.root / "timeout.pid"
        owner = self.run_job("timeout", self.sleeper(marker, ignore_term=True),
                         options=["--time-limit", "0.35"])
        payload = self.remember_payload(marker)
        self.assertNotEqual(owner.wait(5), 0)
        self.assertIsNone(identity(payload[0]))
        self.assertTrue(self.terminal("timeout")["quiescent"])
        self.assertFalse(self.claim("timeout").exists())

    def test_stop_does_not_signal_reused_or_mismatched_identity(self):
        marker = self.root / "identity.pid"
        owner = self.run_job("identity", self.sleeper(marker))
        payload = self.remember_payload(marker)
        path = self.claim("identity")
        original = path.read_text()
        record = json.loads(original)
        record["owner"]["start_ticks"] += 1
        path.write_text(json.dumps(record))
        try:
            stopped = self.stop("identity")
            self.assertNotEqual(stopped.returncode, 0)
            self.assertIsNone(owner.poll())
            self.assertIsNotNone(identity(payload[0]))
            self.assertTrue(path.exists())
        finally:
            path.write_text(original)
        self.assertEqual(self.stop("identity").returncode, 0)
        owner.wait()

    def test_stale_descendant_census_cannot_signal_an_unrelated_same_user_process(self):
        unrelated_marker = self.root / "unrelated.pid"
        unrelated = subprocess.Popen(
            [sys.executable, "-c", self.sleeper(unrelated_marker)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        unrelated_identity = self.remember_payload(unrelated_marker)

        def reap_unrelated():
            signal_owned(unrelated_identity, signal.SIGKILL)
            unrelated.wait(timeout=3)

        self.addCleanup(reap_unrelated)
        marker = self.root / "census-worker.pid"
        owner = self.run_job("stale-census", self.sleeper(marker),
                             stale_census_pid=unrelated.pid)
        self.remember_payload(marker)
        signal_owned(owner.identity, signal.SIGTERM)
        deadline = time.monotonic() + .3
        while owner.poll() is None and unrelated.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNone(unrelated.poll(), "cancellation signaled an unrelated process")
        # The hidden real child cannot be safely signaled through this corrupt
        # census. The supervisor retries only until its bounded shutdown window.
        self.assertNotEqual(owner.wait(13), 0)
        self.assertIsNone(unrelated.poll(), "cancellation signaled an unrelated process")
        self.assertTrue(self.claim("stale-census").exists())
        self.assertFalse(self.terminal("stale-census")["quiescent"])

    def test_required_memory_controls_are_checked_before_user_code(self):
        for name, limits in [
            ("unlimited", {"memory_max": None, "swap_max": None,
                           "cgroup": "/test", "cpus_effective": self.allowed}),
            ("unknown", "unknown"),
        ]:
            with self.subTest(name=name):
                marker = self.root / ("memory-" + name + ".pid")
                call = self.run_job("cap-" + name, self.sleeper(marker), limits=limits,
                                options=["--require-memory-cap", "--require-no-swap"])
                self.assertNotEqual(call.wait(), 0)
                self.assertFalse(marker.exists())
                self.assertFalse(self.claim("cap-" + name).exists())

    def test_effective_controls_are_verified_for_the_gated_worker(self):
        marker, checked = self.root / "gated.pid", self.root / "checked.json"
        limits = {"memory_max": 1024 * 1024, "swap_max": 0,
                  "cgroup": "/test", "cpus_effective": self.allowed}
        code = f"import os; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid()))"
        call = self.run_job("gated", code, limits=limits, memory_probe_marker=checked,
                        options=["--require-memory-cap", "--require-no-swap"])
        self.assertEqual(call.wait(), 0, call.stdout + call.stderr)
        verified = json.loads(checked.read_text())
        self.assertEqual(verified["pid"], int(marker.read_text()))
        self.assertEqual(verified["affinity"], [self.allowed[0]])

    def test_worker_receives_actual_affinity_thread_caps_and_gpu_mapping(self):
        marker = self.root / "effective-worker.json"
        variables = ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                     "NUMEXPR_NUM_THREADS", "JULIA_NUM_THREADS"]
        code = (
            "import json, os; from pathlib import Path; "
            f"Path({str(marker)!r}).write_text(json.dumps({{"
            "'affinity': sorted(os.sched_getaffinity(0)), "
            f"'threads': {{key: os.environ.get(key) for key in {variables!r}}}, "
            "'gpu': os.environ.get('CUDA_VISIBLE_DEVICES')}))"
        )
        call = self.run_job("effective-worker", code, options=["--gpus", "2", "--threads", "1"])
        self.assertEqual(call.wait(), 0, call.stdout + call.stderr)
        result = json.loads(marker.read_text())
        self.assertEqual(result["affinity"], [self.allowed[0]])
        self.assertEqual(result["threads"], dict.fromkeys(variables, "1"))
        self.assertIn(result["gpu"], ["2", "GPU-00000002-0000-0000-0000-000000000000"])

    def test_duplicate_resources_never_deadlock_or_create_duplicate_claims(self):
        cpu = self.allowed[0]
        call = self.run_job("duplicates", "raise SystemExit(0)",
                        options=["--cpus", f"{cpu},{cpu}", "--gpus", "0,0"])
        call.wait(3)
        self.assertFalse(self.claim("duplicates").exists())

    def test_existing_run_directory_and_used_run_id_cannot_overwrite_evidence(self):
        existing = self.root / "existing"
        existing.mkdir()
        sentinel = existing / "precious.txt"
        sentinel.write_text("retained evidence")
        denied = self.run_job("existing", "raise SystemExit(0)")
        self.assertNotEqual(denied.wait(), 0)
        self.assertEqual(sentinel.read_text(), "retained evidence")
        completed = self.run_job("completed", "raise SystemExit(0)")
        self.assertEqual(completed.wait(), 0)
        terminal = (self.root / "completed" / "terminal.json").read_bytes()
        repeated = self.run_job("completed", "raise SystemExit(0)",
                            options=["--run-dir", str(self.root / "different-output")])
        self.assertNotEqual(repeated.wait(), 0)
        self.assertEqual((self.root / "completed" / "terminal.json").read_bytes(), terminal)

    def test_admission_lock_inode_stays_stable_and_claims_omit_command_contents(self):
        gate = self.state / "admission.lock"
        original_inode = (gate.stat().st_dev, gate.stat().st_ino)
        marker = self.root / "private-command.pid"
        code = "sensitive_fixture_value = 'not-a-real-secret'; " + self.sleeper(marker)
        owner = self.run_job("private-command", code)
        self.remember_payload(marker)
        self.assertNotIn("sensitive_fixture_value", self.claim("private-command").read_text())
        self.assertEqual(self.stop("private-command").returncode, 0)
        owner.wait()
        self.assertEqual((gate.stat().st_dev, gate.stat().st_ino), original_inode)

    def test_invalid_budgets_and_path_traversal_do_not_execute_commands(self):
        for index, options in enumerate([
            ["--memory-mib", "0"], ["--threads", "0"],
            ["--time-limit", "0"], ["--wait", "-1"],
            ["--run-id", "../escape"],
        ]):
            with self.subTest(options=options):
                marker = self.root / f"invalid-{index}.pid"
                denied = self.run_job(f"invalid-{index}", self.sleeper(marker), options=options)
                self.assertNotEqual(denied.wait(), 0)
                self.assertFalse(marker.exists())
        self.assertFalse((self.state / "escape.json").exists())

    def test_probe_reports_observation_without_a_reservation(self):
        call = self.call(["probe", "--cpus", str(self.allowed[0])])
        self.assertEqual(call.returncode, 0, call.stdout + call.stderr)
        self.assertIs(call.json()["reservation"], False)
        self.assertFalse(list((self.state / "claims").glob("*.json")))

    def test_unknown_existing_claim_blocks_admission_instead_of_being_ignored(self):
        broken = self.state / "claims" / "broken.json"
        broken.write_text("{not-json")
        marker = self.root / "corrupt-denied.pid"
        call = self.run_job("corrupt-denied", self.sleeper(marker))
        self.assertNotEqual(call.wait(), 0)
        self.assertFalse(marker.exists())
        self.assertEqual(broken.read_text(), "{not-json")


if __name__ == "__main__":
    unittest.main()
