import re
from pathlib import Path

class VaultError(Exception):
    pass

class VaultWriter:
    def __init__(self, readings_dir: Path):
        self.dir = Path(readings_dir)
        self.path: Path | None = None

    def start(self, title: str, meta: dict) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[/:\\]", "-", title).strip()
        self.path = self.dir / f"{safe}.md"
        if not self.path.exists():
            fm = "".join(f"{k}: {v}\n" for k, v in meta.items())
            self.path.write_text(f"---\n{fm}status: reading\n---\n")
        return self.path

    def _append(self, s: str) -> None:
        if self.path is None:
            raise VaultError("no note started")
        self.path.write_text(self.path.read_text() + s)

    def add_highlight(self, text: str) -> None:
        self._append(f'- "{text}"\n')

    def add_annotation(self, kind: str, text: str) -> None:
        self._append(f"\t- {kind}: {text}\n")

    def undo_last_highlight(self) -> None:
        if self.path is None:
            raise VaultError("no note started")
        lines = self.path.read_text().splitlines(keepends=True)
        highlight_indices = [i for i, l in enumerate(lines) if l.startswith('- "')]
        if not highlight_indices:
            return
        idx = max(highlight_indices)
        end = idx + 1
        while end < len(lines) and lines[end].startswith("\t"):
            end += 1
        self.path.write_text("".join(lines[:idx] + lines[end:]))

    def add_section(self, heading: str, body: str) -> None:
        self._append(f"\n## {heading}\n\n{body}\n")

    def set_status(self, status: str) -> None:
        if self.path is None:
            raise VaultError("no note started")
        t = self.path.read_text()
        self.path.write_text(re.sub(r"^status: .*$", f"status: {status}", t, count=1, flags=re.M))
