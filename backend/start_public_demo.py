from __future__ import annotations

import os
import subprocess
import sys


def _run(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)


def main() -> None:
    env = os.environ.copy()
    demo_condominium = env.get("CONDOCHARGE_DEMO_CONDOMINIUM_NAME", "Riverview Residences")

    _run([sys.executable, "-m", "alembic", "upgrade", "head"], env)
    _run(
        [
            sys.executable,
            "-m",
            "condocharge.tools.demo_seed",
            "--condominium-name",
            demo_condominium,
        ],
        env,
    )

    port = env.get("PORT") or env.get("CONDOCHARGE_API_PORT") or "8000"
    server_command = [
        sys.executable,
        "-m",
        "uvicorn",
        "condocharge.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
    ]
    if os.name == "nt":
        _run(server_command, env)
        return
    os.execvpe(sys.executable, server_command, env)


if __name__ == "__main__":
    main()
