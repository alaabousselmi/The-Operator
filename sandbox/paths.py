"""Where the sandbox lives, and the rule that nothing may leave it."""

from pathlib import Path

SANDBOX_DIR = Path(__file__).parent
TEMPLATES = SANDBOX_DIR / "templates"  # clean jobs and data, committed to git
WORK = SANDBOX_DIR / ".work"  # the live sandbox, git-ignored, rebuilt by reset
MARKER = ".sandbox_marker"  # file that proves a folder is a sandbox we may delete


def resolve_inside(work: Path, relative: str) -> Path:
    """Turn a relative path into a real path, refusing anything outside `work`."""
    target = (work / relative).resolve()
    if not target.is_relative_to(work.resolve()):
        raise ValueError(f"path '{relative}' is outside the sandbox")
    return target
