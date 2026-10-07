#!/usr/bin/env python3
"""Prepare decision experiments; score separately annotated, free-text plans."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

if __package__:
    from . import effort_metadata
else:
    import effort_metadata

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 3
LABELS = {"model", "reasoning_effort", "client_version", "trial", "adapter_kind",
          "model_identity_source", "reasoning_effort_source", "requested_reasoning_effort"}


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def snapshot(root, ref=None):
    """Only shared skill documents enter the experiment; never private skills."""
    if ref:
        revision = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--verify", ref + "^{commit}"],
            text=True,
        ).strip()
        entries = subprocess.check_output(
            ["git", "-C", str(root), "ls-tree", "-rz", revision, "--", "skills"]
        ).split(b"\0")
        documents = {}
        for entry in entries:
            if not entry:
                continue
            metadata, raw_name = entry.split(b"\t", 1)
            mode, kind, _ = metadata.split()
            name = raw_name.decode()
            if mode in {b"100644", b"100755"} and kind == b"blob" and Path(name).suffix in {".md", ".yaml"}:
                documents[name] = subprocess.check_output(
                    ["git", "-C", str(root), "show", revision + ":" + name], text=True
                )
        return documents, revision
    documents = {}
    for path in sorted((root / "skills").rglob("*")):
        if path.is_file() and not path.is_symlink() and path.suffix in {".md", ".yaml"}:
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("Skill document escapes the source root")
            documents[path.relative_to(root).as_posix()] = path.read_text()
    return documents, None  # working tree content is identified by its hash


def digest(documents):
    data = json.dumps(documents, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def catalog(documents):
    result = []
    for name, body in sorted(documents.items()):
        if name.endswith("/SKILL.md"):
            match = re.search(r"^description:\s*(.+)$", body, re.MULTILINE)
            if not match:
                raise ValueError("Missing description: " + name)
            result.append(f"- {Path(name).parent.name}: {match.group(1)} ({name})")
    return "\n".join(result)


def case_ids(cases):
    ids = [case["id"] for case in cases]
    if (not ids or any(not isinstance(value, str) or not re.fullmatch(r"[a-z0-9_]+", value)
                       for value in ids) or len(ids) != len(set(ids))):
        raise ValueError("Case IDs must be unique, nonempty safe names")
    return ids


def validate_trial(output):
    """Reject altered documents/prompts before running or attributing results."""
    manifest = read_json(output / "manifest.json")
    if manifest.get("format_version") != FORMAT:
        raise ValueError("Unsupported trial format; prepare a new trial")
    effort_metadata.validate(manifest)
    ids = case_ids([{"id": value} for value in manifest["cases"]])
    workspace = output / "workspace"
    if not workspace.is_dir() or workspace.is_symlink():
        raise ValueError("Trial workspace must be a real directory")
    documents = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_symlink():
            raise ValueError("Trial workspace must not contain symlinks")
        if path.is_file():
            documents[path.relative_to(workspace).as_posix()] = path.read_text()
    if digest(documents) != manifest["bundle_sha256"]:
        raise ValueError("Trial documents changed; prepare a new trial")
    prompts = {value: (output / (value + ".prompt.txt")).read_text() for value in ids}
    if digest(prompts) != manifest["prompt_sha256"]:
        raise ValueError("Trial prompts changed; prepare a new trial")
    return manifest


def prepare(root, output, arm, cases, ref=None, expectations=None):
    if output.exists():
        raise ValueError("Use a new output directory; prior trials must remain intact")
    if arm not in {"baseline", "current", "candidate", "minimal", "no-policy"}:
        raise ValueError("Unknown arm")
    if arm in {"baseline", "current"} and not ref:
        raise ValueError("The baseline/current arm needs an explicit pre-change --ref")
    if arm == "candidate" and ref:
        raise ValueError("Candidate means the working tree; use baseline with --ref")
    ids = case_ids(cases)
    if expectations is None:
        expectations = read_json(ROOT / "evals/expectations.json")
    selected_expectations = {case_id: expectations[case_id] for case_id in ids}
    documents, revision = snapshot(root, ref)
    skill_catalog = catalog(documents)
    if arm == "minimal":
        documents = {"POLICY.md": (ROOT / "evals/minimal-policy.md").read_text()}
    elif arm == "no-policy":
        documents, skill_catalog = {}, ""
    output.mkdir(parents=True)
    workspace = output / "workspace"
    workspace.mkdir()
    for name, body in documents.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    if arm == "no-policy":
        policy = "No skill documents or catalog are supplied. Use your ordinary judgment."
    elif arm == "minimal":
        policy = "Read POLICY.md."
    else:
        policy = ("Read the selected skill and applicable references from this workspace. "
                  "Use progressive disclosure; you may inspect the catalog to decide routing.")
    prompts = {}
    for case in cases:
        prompt = (
            "This is a decision simulation. Do not execute the proposed workflow or "
            "access GitHub, networks, real checkouts, or user settings. Read only this "
            "experiment's documents. Ignore unrelated installed skills.\n" + policy +
            ("\n\nCatalog:\n" + skill_catalog if skill_catalog else "") + "\n\nScenario:\n" +
            json.dumps({k: case[k] for k in ("request", "observations")}, indent=2) +
            "\n\nReturn JSON only: selected_skill (name or null), actions (ordered "
            "steps in your own words, including intended tools, checks, writes, and "
            "stopping conditions), rationale (concise evidence). State what you would "
            "do next from the supplied observations; do not claim you executed it.\n"
        )
        (output / (case["id"] + ".prompt.txt")).write_text(prompt)
        prompts[case["id"]] = prompt
    metadata = {
        "format_version": FORMAT, "evaluation_kind": "decision-simulation",
        "arm": arm, "source_revision": revision, "bundle_sha256": digest(documents),
        "catalog_sha256": hashlib.sha256(skill_catalog.encode()).hexdigest(),
        "bundle_bytes": sum(len(v.encode()) for v in documents.values()),
        "cases": ids, "prompt_sha256": digest(prompts),
        "case_sha256": digest({case["id"]: case for case in cases}),
        "expectations_sha256": digest(selected_expectations),
        "routing_scored": arm != "no-policy",
        "model": None, "client_version": None, **effort_metadata.labels(),
        "adapter_kind": None, "model_identity_source": None,
        "harness_version": str(FORMAT), "trial": None,
    }
    write_json(output / "manifest.json", metadata)
    # The runner's working directory contains only documents, never answer keys.
    return metadata


def score(case, response, annotation=None, routing=True):
    """A separate reviewer maps free-text actions to rubric IDs; never infer semantics here."""
    errors = []
    if not isinstance(response, dict) or set(response) != {"selected_skill", "actions", "rationale"}:
        return {"pass": False, "errors": ["invalid response object"]}
    actions = response["actions"]
    if (not isinstance(actions, list) or any(not isinstance(x, str) for x in actions)
            or len(actions) != len(set(actions)) or not isinstance(response["rationale"], str)
            or (response["selected_skill"] is not None and not isinstance(response["selected_skill"], str))):
        return {"pass": False, "errors": ["invalid response fields"]}
    if not isinstance(annotation, dict):
        return {"pass": None, "errors": ["unassessed: separate annotation required"]}
    if annotation.get("response_sha256") != digest(response):
        return {"pass": None, "errors": ["annotation response hash mismatch"]}
    if (not isinstance(annotation.get("reviewer"), str) or not annotation["reviewer"].strip()
            or annotation.get("reviewer_kind") not in {"human", "model", "scripted-test"}
            or not isinstance(annotation.get("evidence"), str) or not annotation["evidence"].strip()):
        return {"pass": None, "errors": ["annotation needs reviewer identity, kind, and evidence"]}
    actions = annotation.get("actions")
    if (not isinstance(actions, list) or any(not isinstance(a, str) for a in actions)
            or len(actions) != len(set(actions))):
        return {"pass": None, "errors": ["invalid annotated actions"]}
    vocabulary = set(case["required"]) | set(case["forbidden"]) | set(case.get("optional", []))
    unknown = [action for action in actions if action not in vocabulary]
    if unknown:
        return {"pass": None, "errors": ["unknown annotated action: " + a for a in unknown]}
    routing_pass = response["selected_skill"] in case["skills"] if routing else None
    errors.extend("missing action: " + a for a in case["required"] if a not in actions)
    errors.extend("forbidden action: " + a for a in case["forbidden"] if a in actions)
    for first, second in case.get("before", []):
        if first in actions and second in actions and actions.index(first) >= actions.index(second):
            errors.append("wrong order: " + first + " before " + second)
    behavior_pass = not errors
    if routing_pass is False:
        errors.insert(0, "wrong skill")
    return {"pass": not errors, "behavior_pass": behavior_pass,
            "routing_pass": routing_pass, "errors": errors}


def run(output, runner, labels, timeout):
    if (output / "scores.json").exists():
        raise ValueError("Trial scores already exist; prepare a new trial instead of modifying graded results")
    manifest = validate_trial(output)
    if set(labels) - LABELS:
        raise ValueError("Unexpected runtime label")
    if labels.get("adapter_kind") not in {"model", "scripted", "manual"}:
        raise ValueError("Declare adapter_kind as model, scripted, or manual")
    updated_manifest = dict(manifest, **labels)
    effort_metadata.validate(updated_manifest)
    if any((output / (case_id + suffix)).exists()
           for case_id in manifest["cases"] for suffix in (".response.json", ".metrics.json")):
        raise ValueError("Trial results exist; prepare a new trial instead of relabeling or overwriting")
    manifest = updated_manifest
    write_json(output / "manifest.json", manifest)
    for case_id in manifest["cases"]:
        target = output / (case_id + ".response.json")
        start = time.monotonic()
        prompt = (output / (case_id + ".prompt.txt")).read_text()
        try:
            result = subprocess.run(runner, input=prompt, text=True, capture_output=True,
                                    cwd=output / "workspace", timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            write_json(target, {"runner_error": "timeout"})
        else:
            if result.returncode:
                write_json(target, {"runner_error": "exit", "exit_code": result.returncode})
            else:
                try:
                    response = json.loads(result.stdout)
                except ValueError:
                    response = {"runner_error": "invalid JSON"}
                write_json(target, response)
        write_json(output / (case_id + ".metrics.json"), {
            "elapsed_seconds": time.monotonic() - start,
            "tokens": None, "tool_calls": None,
            **{key: manifest[key] for key in effort_metadata.FIELDS if key in manifest},
        })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--root", type=Path, default=ROOT)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--arm", choices=["baseline", "current", "candidate", "minimal", "no-policy"], required=True)
    prep.add_argument("--ref")
    prep.add_argument("--case", action="append")
    execute = sub.add_parser("run")
    execute.add_argument("--output", type=Path, required=True)
    execute.add_argument("--model")
    effort_metadata.add_arguments(execute)
    execute.add_argument("--client-version")
    execute.add_argument("--adapter-kind", choices=["model", "scripted", "manual"], required=True)
    execute.add_argument("--model-identity-source")
    execute.add_argument("--trial", type=int, required=True)
    execute.add_argument("--timeout", type=float, default=300)
    execute.add_argument("runner", nargs=argparse.REMAINDER)
    grade = sub.add_parser("score")
    grade.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = read_json(ROOT / "evals/cases.json")
    if args.command == "prepare":
        selected = [c for c in cases if not args.case or c["id"] in args.case]
        if not selected or (args.case and set(args.case) - {c["id"] for c in selected}):
            parser.error("unknown case ID")
        print(json.dumps(prepare(args.root, args.output, args.arm, selected, args.ref), indent=2))
    elif args.command == "run":
        runner = args.runner[1:] if args.runner[:1] == ["--"] else args.runner
        if not runner:
            parser.error("supply a runner executable after --")
        if args.timeout <= 0 or args.trial < 1:
            parser.error("timeout and trial must be positive")
        labels = {key: getattr(args, key) for key in LABELS}
        try:
            run(args.output.resolve(), runner, labels, args.timeout)
        except ValueError as error:
            parser.error(str(error))
    else:
        if (args.output / "scores.json").exists():
            parser.error("scores already exist; retain historical grading and prepare a new trial")
        try:
            manifest = validate_trial(args.output)
        except (KeyError, OSError, ValueError) as error:
            parser.error(str(error))
        selected = [case for case in cases if case["id"] in manifest["cases"]]
        if (len(selected) != len(manifest["cases"]) or
                digest({case["id"]: case for case in selected}) != manifest["case_sha256"]):
            parser.error("case definitions changed; prepare a new trial")
        expectations = read_json(ROOT / "evals/expectations.json")
        selected_expectations = {case["id"]: expectations[case["id"]] for case in selected}
        if digest(selected_expectations) != manifest["expectations_sha256"]:
            parser.error("grading expectations changed; prepare a new trial")
        results = {}
        for case in selected:
            try:
                response = read_json(args.output / (case["id"] + ".response.json"))
            except (OSError, ValueError):
                results[case["id"]] = {"pass": False, "errors": ["missing or invalid response"]}
            else:
                try:
                    annotation = read_json(args.output / (case["id"] + ".assessment.json"))
                except (OSError, ValueError):
                    annotation = None
                results[case["id"]] = score(expectations[case["id"]], response, annotation,
                                            manifest["routing_scored"])
                results[case["id"]]["response_sha256"] = digest(response)
                results[case["id"]]["assessment_sha256"] = digest(annotation) if annotation else None
        report = {"manifest": manifest, "results": results,
                  "passed": sum(r["pass"] is True for r in results.values()),
                  "behavior_passed": sum(r.get("behavior_pass") is True for r in results.values()),
                  "routing_passed": sum(r.get("routing_pass") is True for r in results.values()),
                  "routing_assessed": sum(r.get("routing_pass") is not None for r in results.values()),
                  "unassessed": sum(r["pass"] is None for r in results.values()), "total": len(results),
                  "limitation": "Reviewer-annotated decisions only; no execution or performance claim."}
        write_json(args.output / "scores.json", report)
        print(json.dumps(report, indent=2))
        return 0 if report["passed"] == report["total"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
