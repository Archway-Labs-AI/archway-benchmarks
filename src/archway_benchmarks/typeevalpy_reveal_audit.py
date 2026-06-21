"""Audit helpers for reveal_type-based TypeEvalPy runners.

The vendored TypeEvalPy pyrefly/pyright runners intentionally emit only
score-submission records. This module adds a side-channel audit record around
that protocol: transformed source, insertion maps, raw reveal diagnostics,
normalized records, and locations dropped because the checker reported
Unknown/Any/Never.

The implementation is runner-agnostic for planning/rendering but currently
ships a pyrefly payload parser because pyrefly was the audited tool.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


UNKNOWN_SENTINELS = frozenset({"Unknown", "Any", "Never", "Unbound"})
PYREFLY_REVEALED_PREFIX = "revealed type: "


@dataclass(frozen=True)
class RevealObservation:
    gt_index: int
    transformed_line: int | None
    raw_type: str
    normalized_types: list[str]
    dropped_reason: str | None = None
    audit_reconciled_types: list[str] | None = None


@dataclass(frozen=True)
class AuditClassification:
    gt_index: int
    kind: str | None
    name: str | None
    function: str | None
    status: str
    expected_types: list[str]
    raw_types: list[str]
    normalized_types: list[str]
    audit_reconciled_types: list[str]


def run_pyrefly_snippet_audit(
    *,
    snippet_dir: Path,
    runner_module: ModuleType,
    out_dir: Path,
    pyrefly_bin: str = "pyrefly",
) -> dict[str, Any]:
    """Run pyrefly on one TypeEvalPy snippet and write audit artifacts.

    ``runner_module`` is the vendored pyrefly runner module. We deliberately
    call its planning/rendering/normalization functions so score-compatible
    output stays tied to the runner under audit.
    """
    snippet_dir = Path(snippet_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    main_py = snippet_dir / "main.py"
    gt_path = snippet_dir / "main_gt.json"
    source = main_py.read_text()
    gt = json.loads(gt_path.read_text())
    tree = ast.parse(source, filename=str(main_py))

    fns = runner_module.collect_functions(tree)
    insertions = []
    insertion_plan = []
    unsupported = classify_unsupported_gt(gt, source)
    for i, entry in enumerate(gt):
        planned = runner_module.plan_insertion(entry, fns, source, tree, i)
        if planned is None:
            insertion_plan.append({"gt_index": i, "entry": entry, "status": unsupported.get(i, "no_probe")})
            continue
        insertions.extend(planned)
        insertion_plan.append(
            {
                "gt_index": i,
                "entry": entry,
                "status": "planned",
                "insertions": [_insertion_to_dict(ins) for ins in planned],
            }
        )

    transformed, line_to_gt, synthetic = runner_module.render_transformed(source, insertions)
    (out_dir / "main_transformed.py").write_text(transformed)
    write_json(out_dir / "insertion_plan.json", insertion_plan)
    write_json(out_dir / "line_to_gt.json", {str(k): v for k, v in sorted(line_to_gt.items())})
    write_json(out_dir / "synthetic.json", {str(k): v for k, v in sorted(synthetic.items())})

    if insertions:
        payload = _run_pyrefly_with_payload(
            snippet_dir=snippet_dir,
            transformed=transformed,
            pyrefly_bin=pyrefly_bin,
            config=getattr(runner_module, "PYREFLY_CONFIG", 'project-includes = ["**/*.py"]\n'),
        )
    else:
        payload = {"errors": []}

    write_json(out_dir / "pyrefly_raw_payload.json", payload)
    normalized = runner_module.parse_pyrefly_payload(payload, line_to_gt, gt, synthetic)
    write_json(out_dir / "main_result.json", normalized)

    observations = parse_pyrefly_reveal_observations(
        payload=payload,
        line_to_gt=line_to_gt,
        flatten=runner_module.flatten_pyrefly_type,
        gt=gt,
        source=source,
    )
    for gt_index, types in synthetic.items():
        observations.append(
            RevealObservation(
                gt_index=gt_index,
                transformed_line=None,
                raw_type="<synthetic>",
                normalized_types=sorted(set(types)),
                audit_reconciled_types=sorted(set(types)),
            )
        )
    write_json(out_dir / "reveal_observations.json", [asdict(o) for o in observations])

    classifications = classify_audit(gt, insertion_plan, observations)
    write_json(out_dir / "classification.json", [asdict(c) for c in classifications])
    summary = summarize_classifications(classifications)
    write_json(out_dir / "summary.json", summary)
    return summary


def parse_pyrefly_reveal_observations(
    *,
    payload: dict[str, Any],
    line_to_gt: dict[int, int],
    flatten,
    gt: list[dict[str, Any]],
    source: str,
) -> list[RevealObservation]:
    observations: list[RevealObservation] = []
    for diag in payload.get("errors", []):
        if diag.get("name") != "reveal-type":
            continue
        desc = diag.get("description", "")
        if not desc.startswith(PYREFLY_REVEALED_PREFIX):
            continue
        line = diag.get("line")
        if line is None:
            continue
        gt_index = line_to_gt.get(line)
        if gt_index is None:
            continue
        raw = desc[len(PYREFLY_REVEALED_PREFIX) :].strip()
        normalized = sorted(set(flatten(raw)))
        dropped_reason = "unknown_any_never" if _is_only_unknown_any_never(raw) else None
        reconciled = reconcile_imported_class_types(
            normalized_types=normalized,
            entry=gt[gt_index],
            source=source,
        )
        observations.append(
            RevealObservation(
                gt_index=gt_index,
                transformed_line=line,
                raw_type=raw,
                normalized_types=normalized,
                dropped_reason=dropped_reason,
                audit_reconciled_types=reconciled,
            )
        )
    return observations


def classify_unsupported_gt(gt: list[dict[str, Any]], source: str) -> dict[int, str]:
    """Classify GT entries that the current FunctionDef-only planner cannot probe."""
    out: dict[int, str] = {}
    tree = ast.parse(source)
    lambda_params: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Lambda):
            continue
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            lambda_params.add((arg.lineno, arg.arg))

    for i, entry in enumerate(gt):
        if entry.get("function") != "lambda" or "parameter" not in entry:
            continue
        key = (entry.get("line_number"), entry.get("parameter"))
        if key in lambda_params:
            out[i] = "unsupported_lambda_parameter_probe"
    return out


def classify_audit(
    gt: list[dict[str, Any]],
    insertion_plan: list[dict[str, Any]],
    observations: list[RevealObservation],
) -> list[AuditClassification]:
    by_gt: dict[int, list[RevealObservation]] = {}
    for obs in observations:
        by_gt.setdefault(obs.gt_index, []).append(obs)
    plan_by_gt = {item["gt_index"]: item for item in insertion_plan}

    out: list[AuditClassification] = []
    for i, entry in enumerate(gt):
        kind, name, function = entry_kind(entry)
        obs = by_gt.get(i, [])
        raw_types = [o.raw_type for o in obs]
        normalized = sorted({t for o in obs for t in o.normalized_types})
        reconciled = sorted({t for o in obs for t in (o.audit_reconciled_types or o.normalized_types)})
        expected = sorted(entry.get("type", []))
        if not obs:
            status = plan_by_gt.get(i, {}).get("status", "no_probe")
        elif not normalized and all(o.dropped_reason == "unknown_any_never" for o in obs):
            status = "unknown_any_never_preserved"
        elif normalized == expected:
            status = "exact_normalized"
        elif reconciled == expected and reconciled != normalized:
            status = "audit_reconciled_imported_class"
        else:
            status = "normalized_type_miss"
        out.append(
            AuditClassification(
                gt_index=i,
                kind=kind,
                name=name,
                function=function,
                status=status,
                expected_types=expected,
                raw_types=raw_types,
                normalized_types=normalized,
                audit_reconciled_types=reconciled,
            )
        )
    return out


def reconcile_imported_class_types(
    *,
    normalized_types: list[str],
    entry: dict[str, Any],
    source: str,
) -> list[str]:
    """Audit-only imported class qualification.

    This does not use GT expected types. It only rewrites a bare class name
    when the target source location is an assignment whose RHS is visibly an
    imported class constructor, e.g. ``a = to_import.A()`` after
    ``import to_import`` or ``a = Alias()`` after ``from mod import A as Alias``.
    """
    if len(normalized_types) != 1 or "variable" not in entry:
        return normalized_types
    bare_type = normalized_types[0]
    if "." in bare_type:
        return normalized_types

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return normalized_types
    imports = _import_bindings(tree)
    assignment_rhs = _assignment_call_for_entry(tree, entry)
    if assignment_rhs is None:
        return normalized_types

    qualified: str | None = None
    if isinstance(assignment_rhs.func, ast.Attribute) and isinstance(assignment_rhs.func.value, ast.Name):
        module_alias = assignment_rhs.func.value.id
        attr = assignment_rhs.func.attr
        module = imports.get(module_alias)
        if module and attr == bare_type:
            qualified = f"{module}.{attr}"
    elif isinstance(assignment_rhs.func, ast.Name):
        bound = imports.get(assignment_rhs.func.id)
        if bound and bound.rsplit(".", 1)[-1] == bare_type:
            qualified = bound

    return [qualified] if qualified else normalized_types


def summarize_classifications(classifications: list[AuditClassification]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_kind_status: dict[str, dict[str, int]] = {}
    for item in classifications:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        kind = item.kind or "unknown"
        by_kind_status.setdefault(kind, {})
        by_kind_status[kind][item.status] = by_kind_status[kind].get(item.status, 0) + 1
    return {
        "total_gt": len(classifications),
        "by_status": dict(sorted(by_status.items())),
        "by_kind_status": {k: dict(sorted(v.items())) for k, v in sorted(by_kind_status.items())},
    }


def entry_kind(entry: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    if "variable" in entry:
        return "variable", entry["variable"], entry.get("function")
    if "parameter" in entry:
        return "parameter", entry["parameter"], entry.get("function")
    if "function" in entry and "variable" not in entry and "parameter" not in entry:
        return "return", entry["function"], entry["function"]
    return None, None, None


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _run_pyrefly_with_payload(
    *,
    snippet_dir: Path,
    transformed: str,
    pyrefly_bin: str,
    config: str,
) -> dict[str, Any]:
    work_root = Path(tempfile.mkdtemp(prefix="typeevalpy_pyrefly_audit_"))
    try:
        shutil.copytree(snippet_dir, work_root / "snippet", dirs_exist_ok=True)
        work_dir = work_root / "snippet"
        work_main = work_dir / "main.py"
        work_main.write_text(transformed)
        (work_dir / "pyrefly.toml").write_text(config)
        proc = subprocess.run(
            [pyrefly_bin, "check", "--output-format", "json", str(work_main)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return _parse_pyrefly_stdout(proc.stdout, proc.stderr)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)


def _parse_pyrefly_stdout(stdout: str, stderr: str) -> dict[str, Any]:
    if not stdout:
        return {"errors": [], "_stderr": stderr}
    text = stdout.strip()
    try:
        payload = json.loads(text)
        payload["_stderr"] = stderr
        return payload
    except json.JSONDecodeError:
        pass
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[: i + 1])
                    payload["_trailing_stdout"] = text[i + 1 :].strip()
                    payload["_stderr"] = stderr
                    return payload
                except json.JSONDecodeError:
                    break
    return {"errors": [], "_stdout_parse_error": text[:1000], "_stderr": stderr}


def _is_only_unknown_any_never(raw: str) -> bool:
    parts = [p.strip(" ()") for p in raw.split("|")]
    return bool(parts) and all(p in UNKNOWN_SENTINELS for p in parts)


def _insertion_to_dict(ins: Any) -> dict[str, Any]:
    return {
        "after_line": ins.after_line,
        "indent": ins.indent,
        "expr": ins.expr,
        "gt_index": ins.gt_index,
    }


def _import_bindings(tree: ast.Module) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                bindings[local] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                bindings[local] = f"{node.module}.{alias.name}"
    return bindings


def _assignment_call_for_entry(tree: ast.Module, entry: dict[str, Any]) -> ast.Call | None:
    target_name = entry.get("variable")
    line = entry.get("line_number")
    if not target_name or not line:
        return None
    for node in ast.walk(tree):
        if getattr(node, "lineno", None) != line:
            continue
        value: ast.AST | None = None
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            value = node.value
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            targets = [node.target]
        if value is None or not isinstance(value, ast.Call):
            continue
        if any(_target_binds_name(target, target_name) for target in targets):
            return value
    return None


def _target_binds_name(target: ast.AST, name: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, ast.Starred):
        return _target_binds_name(target.value, name)
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_binds_name(elt, name) for elt in target.elts)
    return False
