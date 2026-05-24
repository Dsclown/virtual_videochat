#!/usr/bin/env python3
"""从 proto/ 生成 Core 与 Gateway 各自的 gRPC Python 桩。"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO_ROOT = ROOT / "proto"
STAGING = ROOT / "build" / "_grpc_staging"
TARGETS = [
    (ROOT / "backend" / "vtuber" / "grpc" / "v1", "vtuber.grpc.v1"),
    (ROOT / "gateway" / "grpc" / "v1", "gateway.grpc.v1"),
]


def _write_inits(base: Path) -> None:
    for pkg in [base.parent.parent, base.parent, base]:
        init = pkg / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")


def main() -> int:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{PROTO_ROOT}",
        f"--python_out={STAGING}",
        f"--grpc_python_out={STAGING}",
        "vtuber/v1/core.proto",
    ]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=PROTO_ROOT)

    src = STAGING / "vtuber" / "v1"
    for dest, import_prefix in TARGETS:
        dest.mkdir(parents=True, exist_ok=True)
        _write_inits(dest)
        for name in ("core_pb2.py", "core_pb2_grpc.py"):
            shutil.copy2(src / name, dest / name)
        grpc_py = dest / "core_pb2_grpc.py"
        text = grpc_py.read_text(encoding="utf-8")
        text = text.replace(
            "from vtuber.v1 import core_pb2 as vtuber_dot_v1_dot_core__pb2",
            f"from {import_prefix} import core_pb2 as vtuber_dot_v1_dot_core__pb2",
        )
        grpc_py.write_text(text, encoding="utf-8")
        print(f"ok {dest} ({import_prefix})")

    shutil.rmtree(STAGING)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
