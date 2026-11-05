"""Fail-closed probes tested with kernel/driver fixtures, never real GPU work."""

import hashlib
import importlib.util
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "remote_resource_probe", ROOT / "skills/remote-runs/scripts/resource_probe.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
UUID_A = "GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UUID_B = "GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
BOOT = "11111111-2222-3333-4444-555555555555"


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        patcher = mock.patch.object(probe, "PROC_ROOT", self.proc)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write(self.proc / "sys/kernel/random/boot_id", BOOT)

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class IdentityTests(Fixtures):
    def test_host_identity_requires_valid_stable_machine_id(self):
        first, second = self.root / "machine-id", self.root / "dbus-id"
        first.write_text("uninitialized")
        second.write_text("A" * 32 + "\n")
        with mock.patch.object(probe, "MACHINE_ID_PATHS", (first, second)):
            self.assertEqual(probe.host_id(), hashlib.sha256(b"a" * 32).hexdigest())
            second.write_text("0" * 32)
            with self.assertRaises(probe.ProbeError):
                probe.host_id()

    def test_malformed_boot_identity_is_unknown(self):
        self.assertEqual(probe.boot_id(), BOOT)
        for value in ("", "bad", "0" * 32, "00000000-0000-0000-0000-000000000000"):
            self.write(self.proc / "sys/kernel/random/boot_id", value)
            with self.subTest(value=value), self.assertRaises(probe.ProbeError):
                probe.boot_id()

    def stat(self, name="name with (nested) parens)", start=12345):
        fields = ["S"] + ["0"] * 18 + [str(start)] + ["0"] * 5
        return "42 (" + name + ") " + " ".join(fields)

    def test_process_name_spaces_and_parentheses_do_not_shift_start_ticks(self):
        self.write(self.proc / "42/stat", self.stat())
        self.assertEqual(probe.process_identity(42), {
            "pid": 42, "start_ticks": 12345, "boot_id": BOOT, "uid": os.getuid(),
        })

    def test_non_utf8_and_unicode_process_names_preserve_identity(self):
        stat = self.proc / "42/stat"
        stat.parent.mkdir()
        template = self.stat(name="NAME").encode("ascii")
        for name in (b"worker-\xff", "worker-μ".encode("utf-8"), b"x) (\xff)\n"):
            with self.subTest(comm=name):
                stat.write_bytes(template.replace(b"NAME", name))
                self.assertEqual(probe.process_identity(42), {
                    "pid": 42, "start_ticks": 12345, "boot_id": BOOT,
                    "uid": os.getuid(),
                })

    def test_non_ascii_state_or_start_tick_tail_is_rejected(self):
        stat = self.proc / "42/stat"
        stat.parent.mkdir()
        template = self.stat(name="worker").encode("ascii")
        for body in (template.replace(b") S ", b") \xff "),
                     template.replace(b" 12345 ", b" \xff ")):
            with self.subTest(body=body):
                stat.write_bytes(body)
                with self.assertRaises(probe.ProbeError):
                    probe.process_identity(42)

    def test_only_proven_nonexistent_process_returns_none(self):
        self.assertIsNone(probe.process_identity(42))
        (self.proc / "42").mkdir()
        with self.assertRaises(probe.ProbeError):
            probe.process_identity(42)
        self.write(self.proc / "42/stat", "42 (missing fields) S 0")
        with self.assertRaises(probe.ProbeError):
            probe.process_identity(42)

    def test_identity_changing_during_read_is_unknown(self):
        directory = self.proc / "42"
        directory.mkdir()
        real_read = Path.read_text
        samples = iter((self.stat(start=1), self.stat(start=2)))

        def read(path, *args, **kwargs):
            if path == directory / "stat":
                return next(samples)
            return real_read(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", read):
            with self.assertRaises(probe.ProbeError):
                probe.process_identity(42)

    def test_identity_read_failure_does_not_mean_dead(self):
        (self.proc / "42").mkdir()
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("hidden")):
            with self.assertRaises(probe.ProbeError):
                probe.process_identity(42)


class CPUTests(Fixtures):
    def topology(self):
        cpus = self.root / "cpu"
        self.write(cpus / "online", "0-1,8-9")
        for cpu, core, siblings in ((0, 0, "0,8"), (8, 0, "0,8"),
                                    (1, 1, "1,9"), (9, 1, "1,9")):
            directory = cpus / f"cpu{cpu}/topology"
            for name, value in (("physical_package_id", "0"),
                                ("core_id", str(core)),
                                ("thread_siblings_list", siblings)):
                self.write(directory / name, value)
        return cpus

    def test_topology_retains_online_siblings_outside_current_affinity(self):
        with mock.patch.object(probe, "CPU_ROOT", self.topology()):
            with mock.patch.object(os, "sched_getaffinity", return_value={0, 1}):
                result = probe.cpu_topology()
        self.assertEqual(result[0], {"resource_id": "cpu:0:0", "siblings": [0, 8]})
        self.assertEqual(result[8]["resource_id"], result[0]["resource_id"])

    def test_asymmetric_or_missing_topology_fails(self):
        cpus = self.topology()
        with mock.patch.object(probe, "CPU_ROOT", cpus):
            self.write(cpus / "cpu8/topology/thread_siblings_list", "8")
            with self.assertRaises(probe.ProbeError):
                probe.cpu_topology()
            (cpus / "cpu8/topology/core_id").unlink()
            with self.assertRaises(probe.ProbeError):
                probe.cpu_topology()

    def test_offline_siblings_are_not_claimed_as_online_cpus(self):
        cpus = self.topology()
        self.write(cpus / "online", "0-1,8")
        with mock.patch.object(probe, "CPU_ROOT", cpus):
            result = probe.cpu_topology()
        self.assertEqual(result[1]["siblings"], [1])
        self.assertNotIn(9, result)

    def test_cpu_list_parser_rejects_duplicates_and_invalid_ranges(self):
        self.assertEqual(probe.parse_cpu_list("0-2,8"), [0, 1, 2, 8])
        for value in ("", "2-1", "0,0", "0-2,2", "-1", "1,,2", "1-x", "1 ", "1-1000002"):
            with self.subTest(value=value), self.assertRaises(probe.ProbeError):
                probe.parse_cpu_list(value)

    def test_cpu_busy_sample_includes_sibling_and_ignores_guest_double_counting(self):
        before = "cpu0 100 0 0 900 0 0 0 0 100 0\ncpu8 100 0 0 900 0 0 0 0 0 0\n"
        after = "cpu0 100 0 0 1000 0 0 0 0 200 0\ncpu8 150 0 0 950 0 0 0 0 0 0\n"
        with mock.patch.object(probe, "_read", side_effect=[before, after]):
            with mock.patch.object(probe.time, "sleep"):
                result = probe.probe_cpu_idle([0, 8])
        self.assertFalse(result["idle"])
        self.assertEqual(result["busy_percent"], {"0": 0.0, "8": 50.0})

    def test_missing_malformed_stalled_or_reset_cpu_counters_are_unknown(self):
        good = "cpu0 1 0 0 99 0 0 0 0\n"
        for after in ("", "cpu0 invalid 0 0 100 0 0 0 0", good,
                      "cpu0 0 0 0 1 0 0 0 0", good + good):
            with self.subTest(after=after), mock.patch.object(
                probe, "_read", side_effect=[good, after],
            ), mock.patch.object(probe.time, "sleep"):
                with self.assertRaises(probe.ProbeError):
                    probe.probe_cpu_idle([0])

    def test_invalid_cpu_sample_parameters_fail(self):
        for cpus, interval, threshold in (([], .1, 5), ([0, 0], .1, 5),
                                          ([0], 0, 5), ([0], float("nan"), 5),
                                          ([0], .1, 101), ([True], .1, 5)):
            with self.subTest(args=(cpus, interval, threshold)):
                with self.assertRaises(probe.ProbeError):
                    probe.probe_cpu_idle(cpus, interval, threshold)


class GPUTests(unittest.TestCase):
    def response(self, stdout="", returncode=0, stderr=""):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_empty_gpu_request_never_queries_driver(self):
        with mock.patch.object(probe.subprocess, "run") as run:
            self.assertEqual(probe.probe_gpu_idle([]), {"idle": True, "devices": {}})
        run.assert_not_called()

    def test_successful_idle_gpu_maps_validated_uuid_and_process_query(self):
        with mock.patch.object(probe.subprocess, "run", side_effect=[
            self.response(f"0, {UUID_A}, 0, 0\n1, {UUID_B}, 0, 0\n"),
            self.response(f"{UUID_B}, 123\n"),
        ]) as run:
            result = probe.probe_gpu_idle([0])
        self.assertTrue(result["idle"])
        self.assertEqual(result["devices"]["0"]["uuid"], UUID_A)
        self.assertEqual(result["devices"]["0"]["pids"], [])
        self.assertEqual(run.call_count, 2)
        self.assertGreater(run.call_args_list[0].kwargs["timeout"], 0)
        self.assertLessEqual(run.call_args_list[0].kwargs["timeout"], 10)
        self.assertIn("--query-gpu=index,uuid,utilization.gpu,memory.used", run.call_args_list[0].args[0])

    def test_high_utilization_without_process_is_never_overridden_to_idle(self):
        with mock.patch.object(probe.subprocess, "run", side_effect=[
            self.response(f"0, {UUID_A}, 90, 0\n"), self.response(),
        ]):
            self.assertFalse(probe.probe_gpu_idle([0])["idle"])

    def test_compute_process_or_graphics_memory_means_busy(self):
        for memory, processes in ((0, f"{UUID_A}, 456\n"), (10, "")):
            with self.subTest(memory=memory, processes=processes):
                with mock.patch.object(probe.subprocess, "run", side_effect=[
                    self.response(f"0, {UUID_A}, 0, {memory}\n"), self.response(processes),
                ]):
                    self.assertFalse(probe.probe_gpu_idle([0])["idle"])

    def test_explicit_verified_memory_baseline_is_respected(self):
        with mock.patch.object(probe.subprocess, "run", side_effect=[
            self.response(f"0, {UUID_A}, 0, 10\n"), self.response(),
        ]):
            self.assertTrue(probe.probe_gpu_idle([0], max_memory_mib=10)["idle"])

    def test_driver_failure_missing_binary_and_timeout_fail_closed(self):
        for failure in (FileNotFoundError("nvidia-smi"), subprocess.TimeoutExpired("nvidia-smi", 10)):
            with self.subTest(failure=failure), mock.patch.object(probe.subprocess, "run", side_effect=failure):
                with self.assertRaises(probe.ProbeError):
                    probe.gpu_inventory()
        for response in (self.response(returncode=1), self.response(),
                         self.response(f"0, {UUID_A}, 0, 0", stderr="driver warning")):
            with self.subTest(response=response), mock.patch.object(probe.subprocess, "run", return_value=response):
                with self.assertRaises(probe.ProbeError):
                    probe.gpu_inventory()

    def test_malformed_inventory_values_fail_closed(self):
        for body in (f"0, {UUID_A}, N/A, 0", f"0, {UUID_A}, nan, 0",
                     f"0, {UUID_A}, 101, 0", f"0, {UUID_A}, 0, -1",
                     f"0, {UUID_A}, 0", "Invalid device", "0, unknown, 0, 0",
                     f"0, {UUID_A}, 0, 0\n0, {UUID_B}, 0, 0",
                     f"0, {UUID_A}, 0, 0\n1, {UUID_A}, 0, 0"):
            with self.subTest(body=body), mock.patch.object(probe.subprocess, "run", return_value=self.response(body)):
                with self.assertRaises(probe.ProbeError):
                    probe.gpu_inventory()

    def test_invalid_process_visibility_and_query_failure_fail_closed(self):
        for response in (self.response("N/A"), self.response(f"{UUID_A}, N/A"),
                         self.response(f"{UUID_B}, 123"),
                         self.response(f"{UUID_A}, 123\n{UUID_A}, 123"),
                         self.response(returncode=1)):
            with self.subTest(response=response):
                with mock.patch.object(probe.subprocess, "run", side_effect=[
                    self.response(f"0, {UUID_A}, 0, 0"), response,
                ]):
                    with self.assertRaises(probe.ProbeError):
                        probe.probe_gpu_idle([0])

    def test_duplicate_missing_or_invalid_requested_devices_fail(self):
        with mock.patch.object(probe.subprocess, "run") as run:
            for indices in ([0, 0], [-1], [True]):
                with self.subTest(indices=indices), self.assertRaises(probe.ProbeError):
                    probe.probe_gpu_idle(indices)
            run.assert_not_called()
        with mock.patch.object(probe.subprocess, "run", return_value=self.response(f"0, {UUID_A}, 0, 0")):
            with self.assertRaises(probe.ProbeError):
                probe.probe_gpu_idle([1])

    def test_gpu_queries_share_one_overall_deadline(self):
        clock = [100.0]
        timeouts = []

        def query(command, **kwargs):
            timeouts.append(kwargs["timeout"])
            if len(timeouts) == 1:
                clock[0] += 7.0
                return self.response(f"0, {UUID_A}, 0, 0")
            return self.response()

        with mock.patch.object(probe.time, "monotonic", side_effect=lambda: clock[0]):
            with mock.patch.object(probe.subprocess, "run", side_effect=query):
                self.assertTrue(probe.probe_gpu_idle([0], timeout=10)["idle"])
        self.assertEqual(timeouts, [10.0, 3.0])

    def test_expired_gpu_deadline_does_not_start_second_query(self):
        clock = [100.0]

        def query(command, **kwargs):
            clock[0] += 10
            return self.response(f"0, {UUID_A}, 0, 0")

        with mock.patch.object(probe.time, "monotonic", side_effect=lambda: clock[0]):
            with mock.patch.object(probe.subprocess, "run", side_effect=query) as run:
                with self.assertRaises(probe.ProbeError):
                    probe.probe_gpu_idle([0], timeout=10)
        self.assertEqual(run.call_count, 1)

    def test_nonfinite_thresholds_and_nonpositive_timeouts_are_rejected(self):
        with mock.patch.object(probe.subprocess, "run") as run:
            for kwargs in ({"max_util_percent": float("nan")},
                           {"max_memory_mib": float("inf")},
                           {"timeout": 0}, {"timeout": -1}, {"timeout": float("inf")}):
                with self.subTest(kwargs=kwargs), self.assertRaises(probe.ProbeError):
                    probe.probe_gpu_idle([0], **kwargs)
            run.assert_not_called()

    def test_real_fake_driver_process_obeys_query_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            driver = Path(directory) / "nvidia-smi"
            driver.write_text(
                "#!/usr/bin/env python3\nimport sys\n"
                "assert '--format=csv,noheader,nounits' in sys.argv\n"
                "if '--query-gpu=index,uuid,utilization.gpu,memory.used' in sys.argv:\n"
                f"    print('0, {UUID_A}, 0, 0')\n"
                "elif '--query-compute-apps=gpu_uuid,pid' in sys.argv:\n"
                "    pass\n"
                "else:\n    sys.exit(9)\n"
            )
            driver.chmod(0o700)
            with mock.patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ["PATH"]}):
                self.assertTrue(probe.probe_gpu_idle([0], timeout=2)["idle"])


class CgroupTests(Fixtures):
    def cgroup(self, mount_root="/"):
        base = self.root / "cgroups"
        leaf = base / "parent/worker"
        leaf.mkdir(parents=True)
        group = str(PurePosixPath(mount_root) / "parent/worker")
        self.write(self.proc / "42/cgroup", "0::" + group)
        self.write(self.proc / "self/mountinfo", f"1 0 0:1 {mount_root} {base} rw - cgroup2 cgroup rw")
        for path in (base, base / "parent", leaf):
            self.write(path / "memory.max", "max")
            self.write(path / "memory.swap.max", "max")
        self.write(leaf / "cpuset.cpus.effective", "0-1,8-9")
        return base, leaf

    def test_effective_limits_include_ancestors_and_actual_mount_root(self):
        base, leaf = self.cgroup("/delegated")
        self.write(base / "memory.max", "2048")
        self.write(base / "parent/memory.max", "1024")
        self.write(leaf / "memory.max", "4096")
        self.write(base / "parent/memory.swap.max", "0")
        self.assertEqual(probe.effective_memory_limits(42), {
            "memory_max": 1024, "swap_max": 0, "cgroup": str(leaf),
            "cpus_effective": [0, 1, 8, 9],
        })

    def test_explicit_max_is_unlimited_not_missing(self):
        self.cgroup()
        limits = probe.effective_memory_limits(42)
        self.assertIsNone(limits["memory_max"])
        self.assertIsNone(limits["swap_max"])

    def test_missing_controller_or_malformed_limits_fail_closed(self):
        base, leaf = self.cgroup()
        self.write(leaf / "memory.max", "unlimited")
        with self.assertRaises(probe.ProbeError):
            probe.effective_memory_limits(42)
        self.write(leaf / "memory.max", "max")
        for path in (base, base / "parent", leaf):
            (path / "memory.swap.max").unlink()
        with self.assertRaises(probe.ProbeError):
            probe.effective_memory_limits(42)

    def test_cpu_set_can_inherit_from_an_ancestor_but_not_be_unknown(self):
        base, leaf = self.cgroup()
        (leaf / "cpuset.cpus.effective").unlink()
        with self.assertRaises(probe.ProbeError):
            probe.effective_memory_limits(42)
        self.write(base / "cpuset.cpus.effective", "2-3")
        self.assertEqual(probe.effective_memory_limits(42)["cpus_effective"], [2, 3])

    def test_missing_unified_path_and_escape_are_unknown(self):
        self.cgroup()
        for membership in ("2:memory:/worker", "0::/../../escape", "0::relative", "0::/\n0::/worker"):
            self.write(self.proc / "42/cgroup", membership)
            with self.subTest(membership=membership), self.assertRaises(probe.ProbeError):
                probe.effective_memory_limits(42)


if __name__ == "__main__":
    unittest.main()
