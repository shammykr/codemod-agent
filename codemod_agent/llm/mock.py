"""Offline stand-in for an LLM.

Returns plausible, context-aware rewrites for each rule so the full pipeline
(generation -> validation -> build check -> diff) runs without an API key. Like a
real model it is not always right: e.g. it rewrites ``os.path.join`` to a ``Path``
expression, which changes the return type and may be caught by the build check.
The response goes through the same JSON parser as real model output.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable

from codemod_agent.analyzers.python import PY2_BUILTINS, UNITTEST_ALIASES
from codemod_agent.llm.base import ChangeRequest, LLMProvider, Suggestion
from codemod_agent.llm.prompts import parse_response

Rewrite = Callable[[ChangeRequest], tuple[str, list[str]] | None]


def _sub_target(req: ChangeRequest, new: str) -> str:
    return req.finding.snippet.replace(req.finding.target, new, 1)


def _src(node: ast.AST, text: str) -> str:
    return ast.get_source_segment(text, node) or ""


def _os_path(req: ChangeRequest) -> tuple[str, list[str]] | None:
    t = req.finding.target
    call = ast.parse(t, mode="eval").body
    if not isinstance(call, ast.Call) or not call.args or not isinstance(call.func, ast.Attribute):
        return None
    args = [_src(a, t) for a in call.args]
    base = f"Path({args[0]})"
    exprs = {
        "join": " / ".join([base, *args[1:]]),
        "exists": f"{base}.exists()",
        "isfile": f"{base}.is_file()",
        "isdir": f"{base}.is_dir()",
        "basename": f"{base}.name",
        "dirname": f"{base}.parent",
        "abspath": f"{base}.resolve()",
        "getsize": f"{base}.stat().st_size",
    }
    new = exprs.get(call.func.attr)
    return (_sub_target(req, new), ["from pathlib import Path"]) if new else None


SPEC_RE = re.compile(r"%(?:\((\w+)\))?([-+ 0#]*\d*(?:\.\d+)?)([sdirf%])")


def _percent_format(req: ChangeRequest) -> tuple[str, list[str]] | None:
    t = req.finding.target
    node = ast.parse(t, mode="eval").body
    if not isinstance(node, ast.BinOp) or not isinstance(node.left, ast.Constant):
        return None
    fmt = node.left.value
    if not isinstance(fmt, str):
        return None
    values = node.right.elts if isinstance(node.right, ast.Tuple) else [node.right]
    exprs = [_src(v, t) for v in values]
    out, pos, idx = [], 0, 0
    for m in SPEC_RE.finditer(fmt):
        if m.group(1):  # %(name)s mapping style: leave for a human
            return None
        out.append(fmt[pos : m.start()].replace("{", "{{").replace("}", "}}"))
        pos = m.end()
        flags, conv = m.group(2), m.group(3)
        if conv == "%":
            out.append("%")
            continue
        if idx >= len(exprs):
            return None
        expr = exprs[idx]
        idx += 1
        if conv == "r":
            out.append(f"{{{expr}!r}}")
        elif conv in "sdi" and not flags:
            out.append(f"{{{expr}}}")
        else:
            spec = {"i": "d", "s": ""}.get(conv, conv)
            out.append(f"{{{expr}:{flags}{spec}}}")
    if idx != len(exprs):
        return None
    out.append(fmt[pos:].replace("{", "{{").replace("}", "}}"))
    body = "".join(out)
    quote = "'" if '"' in body else '"'
    if quote in body or "\\" in body or "\n" in body:
        return None
    return _sub_target(req, f"f{quote}{body}{quote}"), []


def _unittest_alias(req: ChangeRequest) -> tuple[str, list[str]] | None:
    t = req.finding.target
    for old, new in UNITTEST_ALIASES.items():
        if f".{old}(" in t and old != "assertDictContainsSubset":
            return _sub_target(req, t.replace(f".{old}(", f".{new}(", 1)), []
    return None


def _object_base(req: ChangeRequest) -> tuple[str, list[str]] | None:
    s = req.finding.snippet
    new = re.sub(r"\(\s*object\s*\)", "", s, count=1)
    if new == s:
        new = re.sub(r"\bobject\s*,\s*|,\s*object\b", "", s, count=1)
    return (new, []) if new != s else None


def _super(req: ChangeRequest) -> tuple[str, list[str]] | None:
    return _sub_target(req, "super()"), []


def _future(req: ChangeRequest) -> tuple[str, list[str]] | None:
    indent = re.match(r"\s*", req.finding.snippet)
    if "annotations" in req.finding.target:
        return f"{indent.group(0) if indent else ''}from __future__ import annotations\n", []
    return "", []


def _has_key(req: ChangeRequest) -> tuple[str, list[str]] | None:
    t = req.finding.target
    call = ast.parse(t, mode="eval").body
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return None
    return _sub_target(req, f"{_src(call.args[0], t)} in {_src(call.func.value, t)}"), []


def _py2_builtin(req: ChangeRequest) -> tuple[str, list[str]] | None:
    old = req.finding.target
    return re.sub(rf"\b{old}\b", PY2_BUILTINS[old], req.finding.snippet), []


def _utcnow(req: ChangeRequest) -> tuple[str, list[str]] | None:
    t = req.finding.target
    if t.startswith("datetime.datetime."):
        return _sub_target(req, "datetime.datetime.now(datetime.timezone.utc)"), []
    prefix = t.rsplit(".utcnow", 1)[0]
    return _sub_target(req, f"{prefix}.now(timezone.utc)"), ["from datetime import timezone"]


def _js_var(req: ChangeRequest) -> tuple[str, list[str]] | None:
    return re.sub(r"\bvar(\s+)", r"let\1", req.finding.snippet, count=1), []


def _js_eq(req: ChangeRequest) -> tuple[str, list[str]] | None:
    op = req.finding.target
    pattern = rf"(?<![=!<>]){re.escape(op)}(?!=)(?!\s*(?:null|undefined)\b)"
    return re.sub(pattern, op + "=", req.finding.snippet, count=1), []


def _js_buffer(req: ChangeRequest) -> tuple[str, list[str]] | None:
    return _sub_target(req, "Buffer.from("), []


def _js_isarray(req: ChangeRequest) -> tuple[str, list[str]] | None:
    return _sub_target(req, "Array.isArray("), []


def _dep_bump(req: ChangeRequest) -> tuple[str, list[str]] | None:
    m = re.search(r" to (\S+)\.$", req.finding.recommendation)
    return (_sub_target(req, m.group(1)), []) if m else None


REWRITES: dict[str, Rewrite] = {
    "PY001": _os_path,
    "PY002": _percent_format,
    "PY003": _unittest_alias,
    "PY004": _object_base,
    "PY005": _super,
    "PY006": _future,
    "PY007": _has_key,
    "PY008": _py2_builtin,
    "PY010": _utcnow,
    "JS001": _js_var,
    "JS002": _js_eq,
    "JS003": _js_buffer,
    "JS004": _js_isarray,
    "DEP001": _dep_bump,
}


class MockProvider(LLMProvider):
    name = "mock"

    def suggest(self, request: ChangeRequest) -> Suggestion | None:
        rewrite = REWRITES.get(request.finding.rule)
        try:
            result = rewrite(request) if rewrite else None
        except (SyntaxError, IndexError, KeyError):
            result = None
        if result is None:
            reply = json.dumps({"replacement": None})
        else:
            reply = json.dumps(
                {
                    "replacement": result[0],
                    "imports": result[1],
                    "explanation": request.finding.recommendation,
                }
            )
        return parse_response(reply)
