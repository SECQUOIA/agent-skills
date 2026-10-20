"""Scripted, local Git exercises for delegation invariants; not a scheduler.

The unittest driver supplies the decisions, assignments, and synchronization.
No installed skill imports this file. Results say nothing about model behavior
or cross-session publication serialization; no remote or GitHub tool is invoked.
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import subprocess
from threading import Barrier, Event


def git(directory, *args, check=True):
    # Keep the disposable repository independent of operator Git configuration.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0")
    return subprocess.run(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "commit.gpgsign=false", *args],
        cwd=directory, env=env, text=True, capture_output=True, check=check, timeout=15,
    )


def revision(directory, value="HEAD"):
    return git(directory, "rev-parse", value).stdout.strip()


def snapshot(directory):
    """Include dirty tracked/untracked bytes, index, branch, and commit identity."""
    names = git(directory, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
    files = {}
    for name in sorted(set(names.rstrip("\0").split("\0"))):
        path = directory / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {"head": revision(directory), "branch": git(directory, "branch", "--show-current").stdout,
            "index": git(directory, "ls-files", "--stage").stdout,
            "status": git(directory, "status", "--porcelain=v1").stdout, "files": files}


class Exercise:
    """Owned disposable checkouts only; the tests act as the single integrator."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir()  # Refuse to reuse any existing trial directory.
        self.repo = self.root / "user"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "user-work")
        git(self.repo, "config", "user.name", "Fixture")
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        for name, body in {
            "left.txt": "left baseline\n", "right.txt": "right baseline\n",
            "producer.py": "def encode(n):\n    return {'value': n}\n",
            "consumer.py": "def decode(message):\n    return message['value']\n",
            "notes.txt": "user baseline\n",
        }.items():
            (self.repo / name).write_text(body)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "Disposable fixture baseline")
        self.base = revision(self.repo)
        self.integration = self.checkout("integration", self.base)
        (self.repo / "notes.txt").write_text("uncommitted user notes\n")
        (self.repo / "scratch.txt").write_text("untracked user notes\n")
        self.original = snapshot(self.repo)

    def checkout(self, name, start):
        directory = self.root / name
        git(self.repo, "worktree", "add", "-b", "fixture/" + name, str(directory), start)
        return directory

    def assignment(self, name, changes):
        return {"directory": self.checkout(name, self.base), "base": self.base,
                "branch": "fixture/" + name, "changes": changes}

    def work(self, assignment, barrier=None, written=None, release=None, cancel=None,
             finish_changes=None):
        """A real writer can remain active after a cancellation message arrives."""
        directory = assignment["directory"]
        if barrier is not None:
            barrier.wait(timeout=10)
        for name, body in assignment["changes"].items():
            (directory / name).write_text(body)
        if written is not None:
            written.set()
        if release is not None and not release.wait(timeout=10):
            raise TimeoutError("Test driver did not release the active writer")
        for name, body in (finish_changes or {}).items():
            # An already dispatched operation can still finish after cancellation.
            (directory / name).write_text(body)
        if cancel is not None and cancel.is_set():
            # Stop only here, after finishing the outstanding write. The Future
            # completes after return; request receipt alone is not this event.
            return {"state": "interrupted", "base": assignment["base"],
                    "directory": str(directory), "partial": snapshot(directory)}
        git(directory, "add", "--", *assignment["changes"])
        git(directory, "commit", "-m", "Scripted worker change")
        return {"state": "complete", "base": assignment["base"],
                "source_tree": revision(directory, assignment["base"] + "^{tree}"),
                "commit": revision(directory), "tree": revision(directory, "HEAD^{tree}"),
                "directory": str(directory), "branch": assignment["branch"],
                "paths": sorted(assignment["changes"])}

    def workers(self, assignments, parallel):
        if not parallel:
            return [self.work(item) for item in assignments]
        barrier = Barrier(len(assignments))
        with ThreadPoolExecutor(max_workers=len(assignments)) as pool:
            futures = [pool.submit(self.work, item, barrier) for item in assignments]
            return [future.result(timeout=15) for future in futures]

    def solo(self, changes):
        """The equivalent work needs one checkout and no worker assignments."""
        for patch in changes:
            for name, body in patch.items():
                (self.integration / name).write_text(body)
            git(self.integration, "add", "--", *patch)
            git(self.integration, "commit", "-m", "Scripted sequential change")
        return {"state": "integrated", "commit": revision(self.integration),
                "tree": revision(self.integration, "HEAD^{tree}")}

    def integrate(self, results, current_source=None):
        """Exercise one coordinator's bounded sequence, retaining worker refs.

        An upstream source change is quarantined for review rather than silently
        reclassified as verified. This conservative fixture does not implement
        the selective evidence reuse that a real agent may establish by review.
        """
        if any(item["state"] != "complete" for item in results):
            return {"state": "quarantined", "reason": "incomplete worker result"}
        if current_source is not None and any(item["base"] != current_source for item in results):
            return {"state": "quarantined", "reason": "source changed; evidence needs review"}
        for item in results:
            directory = Path(item["directory"])
            if revision(directory) != item["commit"] or git(directory, "status", "--porcelain").stdout:
                return {"state": "quarantined", "reason": "worker changed after handoff"}
        # One cherry-pick sequence allows abort to restore the integration start,
        # including earlier picks in this attempt. Worker commits stay reachable.
        before = revision(self.integration)
        attempt = git(self.integration, "cherry-pick", *[item["commit"] for item in results], check=False)
        if attempt.returncode:
            conflict = git(self.integration, "status", "--porcelain").stdout
            git(self.integration, "cherry-pick", "--abort")
            return {"state": "conflict", "status": conflict, "start": before,
                    "restored": revision(self.integration)}
        return {"state": "integrated", "commit": revision(self.integration),
                "tree": revision(self.integration, "HEAD^{tree}")}

    def interrupted_worker(self, assignment, finish_changes):
        """Return actual observations before and after the writer stops."""
        written, release, cancel = Event(), Event(), Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.work, assignment, written=written, release=release,
                                 cancel=cancel, finish_changes=finish_changes)
            try:
                if not written.wait(timeout=10):
                    raise TimeoutError("Writer did not reach its outstanding operation")
                cancel.set()
                while_active = {"cancellation_requested": True, "stopped": future.done(),
                                "directory_exists": assignment["directory"].exists(),
                                "partial": snapshot(assignment["directory"])}
            finally:
                release.set()
            result = future.result(timeout=15)
        return while_active, result
