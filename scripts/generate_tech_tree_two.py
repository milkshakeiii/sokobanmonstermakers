#!/usr/bin/env python3
"""Generate tech tree JSON from the Django tech_tree_two source."""

from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CarryoverSpec:
    variety: str
    additions: set[str] = field(default_factory=set)


def to_snake(name: str) -> str:
    return name.replace("__", "_").lower()


def normalize_tag_list(tags: list[Any]) -> list[str]:
    result: list[str] = []
    for tag in tags:
        if tag is None:
            continue
        if isinstance(tag, str):
            if tag not in result:
                result.append(tag)
            continue
        if isinstance(tag, list):
            for entry in tag:
                if entry is None:
                    continue
                entry_str = str(entry)
                if entry_str not in result:
                    result.append(entry_str)
            continue
        result.append(str(tag))
    return result


def ensure_additions(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, set):
        return {str(item) for item in value}
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, tuple):
        return {str(item) for item in value}
    return {str(value)}


def evaluate_expr(node: ast.AST, varieties: dict[str, set[str]]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in {"True", "False", "None"}:
            return eval(node.id)
        return node.id

    if isinstance(node, ast.List):
        return [evaluate_expr(elt, varieties) for elt in node.elts]

    if isinstance(node, ast.Tuple):
        return [evaluate_expr(elt, varieties) for elt in node.elts]

    if isinstance(node, ast.Dict):
        return {
            evaluate_expr(key, varieties): evaluate_expr(value, varieties)
            for key, value in zip(node.keys, node.values)
        }

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -evaluate_expr(node.operand, varieties)

    if isinstance(node, ast.BinOp):
        left = evaluate_expr(node.left, varieties)
        right = evaluate_expr(node.right, varieties)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise ValueError(f"Unsupported binary op: {ast.dump(node.op)}")

    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Attribute) and node.attr == "value":
            return evaluate_expr(node.value, varieties)
        if isinstance(node.value, ast.Name):
            if node.value.id in {"TransferableSkills", "AppliedSkills"}:
                return to_snake(node.attr)
        return to_snake(node.attr)

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name == "add_variety":
                new_varieties = evaluate_expr(node.args[0], varieties)
                name = evaluate_expr(node.args[1], varieties)
                if not isinstance(new_varieties, list):
                    new_varieties = [new_varieties]
                for variety in new_varieties:
                    key = str(variety)
                    if key not in varieties:
                        varieties[key] = set()
                    varieties[key].add(str(name))
                return str(name)
            if func_name == "Carryover":
                variety = evaluate_expr(node.args[0], varieties)
                return CarryoverSpec(str(variety))
            if func_name == "set":
                items = evaluate_expr(node.args[0], varieties)
                return set(items if isinstance(items, list) else [items])
            if func_name == "list":
                return list(evaluate_expr(node.args[0], varieties))
            if func_name in {"int", "float"}:
                return getattr(__builtins__, func_name)(evaluate_expr(node.args[0], varieties))

        if isinstance(node.func, ast.Attribute) and node.func.attr == "plus":
            base = evaluate_expr(node.func.value, varieties)
            additions = evaluate_expr(node.args[0], varieties) if node.args else None
            if isinstance(base, CarryoverSpec):
                base.additions.update(ensure_additions(additions))
                return base
            raise ValueError("Unexpected Carryover.plus target")

    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


def resolve_carryover(entry: Any, varieties: dict[str, set[str]]) -> list[str]:
    if isinstance(entry, CarryoverSpec):
        base = varieties.get(entry.variety, set())
        tags = set(base)
        tags.update(entry.additions)
        return sorted(tags)
    if isinstance(entry, list):
        return [str(item) for item in entry]
    return [str(entry)]


def resolve_good_type(record: dict[str, Any], varieties: dict[str, set[str]]) -> dict[str, Any]:
    resolved = dict(record)

    for key in ("type_tags",):
        if key in resolved:
            resolved[key] = normalize_tag_list(resolved[key])

    if "input_goods_tags_required" in resolved:
        resolved["input_goods_tags_required"] = [
            normalize_tag_list(group) for group in resolved["input_goods_tags_required"]
        ]

    if "input_goods_tags_carryover" in resolved:
        resolved["input_goods_tags_carryover"] = [
            resolve_carryover(group, varieties) for group in resolved["input_goods_tags_carryover"]
        ]

    if "tools_required_tags" in resolved:
        resolved["tools_required_tags"] = [
            normalize_tag_list(group) for group in resolved["tools_required_tags"]
        ]

    size = resolved.get("size")
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        try:
            width = int(size[0])
        except (TypeError, ValueError):
            width = 2
        try:
            height = int(size[1])
        except (TypeError, ValueError):
            height = 1
        resolved["size"] = [max(1, width), max(1, height)]
    else:
        resolved["size"] = [2, 1]

    return resolved


def extract_good_types(tree: ast.AST) -> list[ast.Call]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "good_types":
                    if isinstance(node.value, ast.List):
                        calls = []
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Call):
                                calls.append(elt)
                        return calls
    raise RuntimeError("Could not locate good_types list in tech_tree_two.py")


def call_to_record(call: ast.Call, varieties: dict[str, set[str]]) -> dict[str, Any]:
    if not isinstance(call.func, ast.Name) or call.func.id != "GoodType":
        raise ValueError("Unexpected call in good_types list")
    record: dict[str, Any] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            continue
        record[keyword.arg] = evaluate_expr(keyword.value, varieties)
    return record


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: generate_tech_tree_two.py <tech_tree_two.py> <output_json>")
        return 1

    source_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    text = source_path.read_text()

    tree = ast.parse(text, filename=str(source_path))
    varieties: dict[str, set[str]] = {}

    calls = extract_good_types(tree)
    raw_records: list[dict[str, Any]] = []
    for call in calls:
        raw_records.append(call_to_record(call, varieties))

    resolved = [resolve_good_type(record, varieties) for record in raw_records]

    payload = {"good_types": resolved}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Wrote {len(resolved)} good types to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
