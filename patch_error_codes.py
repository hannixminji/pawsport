"""
patch_error_codes.py

Automatically adds error_code=ErrorCode.X to every raise statement that
matches a known message from raise_reference.py.

Usage:
    python patch_error_codes.py

Run from the root of the project (where src/ lives).
Dry-run by default — pass --apply to write changes.
"""

import argparse
import ast
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Step 1: parse raise_reference.py to build message -> error_code mapping
# ---------------------------------------------------------------------------

REFERENCE_FILE = Path("raise_reference.py")

EXCEPTION_CLASSES = {
    "InvalidInputError",
    "NotFoundError",
    "DuplicateValueError",
    "UnauthorizedError",
    "UnauthorizedException",
    "ForbiddenError",
    "ForbiddenException",
    "RateLimitException",
    "TransientDatabaseError",
    "NonTransientDatabaseError",
    "MLServiceError",
    "CustomException",
}

def parse_reference(path: Path) -> dict[tuple[str, str], str]:
    """Returns {(ExceptionClass, message): 'ErrorCode.X'}"""
    mapping: dict[tuple[str, str], str] = {}
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise):
            continue
        exc = node.exc
        if not isinstance(exc, ast.Call):
            continue
        if not isinstance(exc.func, ast.Name):
            continue

        cls_name = exc.func.id
        if cls_name not in EXCEPTION_CLASSES:
            continue

        # Only process raises that already have error_code= (they're the reference)
        error_code_val = None
        for kw in exc.keywords:
            if kw.arg == "error_code":
                if isinstance(kw.value, ast.Attribute):
                    error_code_val = f"ErrorCode.{kw.value.attr}"
                break

        if error_code_val is None:
            continue

        # Get the message (first positional arg or 'detail' kwarg)
        msg = None
        if exc.args and isinstance(exc.args[0], ast.Constant):
            msg = exc.args[0].value
        else:
            for kw in exc.keywords:
                if kw.arg == "detail" and isinstance(kw.value, ast.Constant):
                    msg = kw.value.value
                    break

        if msg is not None:
            mapping[(cls_name, msg)] = error_code_val

    return mapping


# ---------------------------------------------------------------------------
# Step 2: patch source files
# ---------------------------------------------------------------------------

def make_pattern(cls: str, msg: str) -> re.Pattern:
    escaped_msg = re.escape(msg)
    # Match: raise ClassName("msg") or raise ClassName('msg')
    # that does NOT already have error_code=
    return re.compile(
        rf'(raise\s+{re.escape(cls)}\s*\(\s*(["\']){escaped_msg}\2\s*\))',
        re.MULTILINE,
    )


def patch_file(path: Path, mapping: dict[tuple[str, str], str], apply: bool) -> list[str]:
    source = path.read_text(encoding="utf-8")
    original = source
    changes = []

    for (cls, msg), error_code in mapping.items():
        pattern = make_pattern(cls, msg)

        def replacer(m, _cls=cls, _msg=msg, _ec=error_code):
            quote = m.group(2)
            return f'raise {_cls}({quote}{_msg}{quote}, error_code={_ec})'

        new_source, count = pattern.subn(replacer, source)
        if count:
            changes.append(f"  {cls}('{msg}') -> +error_code={error_code}  ({count}x)")
            source = new_source

    if changes and apply:
        path.write_text(source, encoding="utf-8")

    return changes


def patch_all(src_root: Path, mapping: dict, apply: bool):
    total_files = 0
    total_changes = 0

    for py_file in sorted(src_root.rglob("*.py")):
        # Skip reference and migration files
        if py_file.name in ("raise_reference.py", "patch_error_codes.py"):
            continue
        if "migrations" in py_file.parts or "alembic" in py_file.parts:
            continue

        changes = patch_file(py_file, mapping, apply)
        if changes:
            total_files += 1
            total_changes += len(changes)
            print(f"\n{'[PATCHED]' if apply else '[WOULD PATCH]'} {py_file}")
            for c in changes:
                print(c)

    print(f"\n{'Applied' if apply else 'Dry run'}: {total_changes} changes across {total_files} files.")
    if not apply:
        print("Run with --apply to write changes.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes to files")
    parser.add_argument("--src", default="src", help="Source root (default: src)")
    parser.add_argument("--reference", default="raise_reference.py", help="Path to raise_reference.py")
    args = parser.parse_args()

    reference_path = Path(args.reference)
    if not reference_path.exists():
        print(f"ERROR: reference file not found: {reference_path}", file=sys.stderr)
        sys.exit(1)

    src_root = Path(args.src)
    if not src_root.exists():
        print(f"ERROR: src root not found: {src_root}", file=sys.stderr)
        sys.exit(1)

    mapping = parse_reference(reference_path)
    print(f"Loaded {len(mapping)} message->error_code mappings from {reference_path}")

    patch_all(src_root, mapping, apply=args.apply)


if __name__ == "__main__":
    main()
