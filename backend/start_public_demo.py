from __future__ import annotations

import os
import subprocess
import sys


def _run(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)


def main() -> None:
    env = os.environ.copy()
    env["CONDOCHARGE_RUNTIME_ENTRYPOINT"] = "start_public_demo.py"
    deployment = (env.get("CONDOCHARGE_DEPLOYMENT") or "demo").strip().lower()
    demo_condominium = env.get("CONDOCHARGE_DEMO_CONDOMINIUM_NAME", "Riverview Residences")
    bootstrap_condominium = (env.get("CONDOCHARGE_BOOTSTRAP_CONDOMINIUM_NAME") or "").strip()
    bootstrap_admin_username = env.get("CONDOCHARGE_BOOTSTRAP_ADMIN_USERNAME") or ""
    bootstrap_admin_password = env.get("CONDOCHARGE_BOOTSTRAP_ADMIN_PASSWORD") or ""
    bootstrap_admin_email = env.get("CONDOCHARGE_BOOTSTRAP_ADMIN_EMAIL") or ""

    _run([sys.executable, "-m", "alembic", "upgrade", "head"], env)

    if deployment == "demo":
        _run(
            [
                sys.executable,
                "-m",
                "condocharge.tools.demo_seed",
                "--mode",
                "demo",
                "--condominium-name",
                demo_condominium,
            ],
            env,
        )
    elif deployment == "production":
        if (bootstrap_admin_username or bootstrap_admin_password or bootstrap_admin_email) and not bootstrap_condominium:
            raise RuntimeError(
                "CONDOCHARGE_BOOTSTRAP_CONDOMINIUM_NAME is required when bootstrap admin settings are configured."
            )
        if bootstrap_condominium:
            seed_command = [
                sys.executable,
                "-m",
                "condocharge.tools.demo_seed",
                "--mode",
                "bootstrap",
                "--condominium-name",
                bootstrap_condominium,
            ]
            if bootstrap_admin_username and bootstrap_admin_password:
                seed_command.extend(
                    [
                        "--admin-username",
                        bootstrap_admin_username,
                        "--admin-password",
                        bootstrap_admin_password,
                    ]
                )
                if bootstrap_admin_email:
                    seed_command.extend(["--admin-email", bootstrap_admin_email])
            _run(seed_command, env)
    else:
        raise RuntimeError(
            "Invalid CONDOCHARGE_DEPLOYMENT. Expected 'demo' or 'production'. "
            f"Got: {deployment!r}"
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
