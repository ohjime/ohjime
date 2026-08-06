"""Small command dispatcher used by the repository's Ubuntu Make targets."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


SOURCE_DIR = Path(__file__).resolve().parent
INSTALLER = SOURCE_DIR / "deploy" / "install.sh"
TELEGRAM_CONFIGURATOR = SOURCE_DIR / "configure_telegram_env.py"
TELEGRAM_COMMAND_REGISTRAR = SOURCE_DIR / "register_telegram_commands.py"
VENV_PYTHON = SOURCE_DIR / ".venv" / "bin" / "python"


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def require_ubuntu() -> int | None:
    if platform.system() != "Linux":
        return fail("these commands must be run on the Ubuntu server, not macOS")
    if shutil.which("sudo") is None:
        return fail("sudo is required")
    return None


def call(command: Sequence[str]) -> int:
    """Run one interactive child process and preserve its exit status."""

    try:
        return subprocess.run(list(command), check=False).returncode
    except OSError as error:
        return fail(f"could not start {Path(command[0]).name}: {error.strerror or error}")


def setup(installer_args: Sequence[str]) -> int:
    return call(["sudo", str(INSTALLER), *installer_args])


def telegram_env() -> int:
    if not VENV_PYTHON.is_file():
        return fail("run 'make setup' first")
    result = call(["sudo", str(VENV_PYTHON), str(TELEGRAM_CONFIGURATOR)])
    return result if result else telegram_commands()


def telegram_commands() -> int:
    if not VENV_PYTHON.is_file():
        return fail("run 'make setup' first")
    return call(["sudo", str(VENV_PYTHON), str(TELEGRAM_COMMAND_REGISTRAR)])


def run_services() -> int:
    result = call(["sudo", str(INSTALLER), "--no-start"])
    return result if result else telegram_commands()


def main(arguments: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    commands = {"setup", "telegram-env", "telegram-commands", "run"}
    if not args or args[0] not in commands:
        return fail("usage: ubuntu_commands.py {setup|telegram-env|telegram-commands|run}")
    if problem := require_ubuntu():
        return problem

    command, *extra = args
    if command == "setup":
        return setup(extra)
    if extra:
        return fail(f"'{command}' does not accept additional arguments")
    if command == "telegram-env":
        return telegram_env()
    if command == "telegram-commands":
        return telegram_commands()
    return run_services()


if __name__ == "__main__":
    raise SystemExit(main())
