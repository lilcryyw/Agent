"""Банк навыков — то, чему Джарвис научился сам (Alita, MUSE-Autoskill, Agent Skills).

Навык — обычный Python-пакет в data/skills/<имя>/:
  SKILL.md          — что умеет, когда применять, как вызывать; в шапке — замки (money/message/delete)
  __init__.py       — код
  tests/test_skill.py — тесты (функции test_*), без них навык не принимается
  .memory.md        — заметки опыта: на чём спотыкался, особенности (копятся при использовании)
Допуск: тесты прогоняются в мастерской; прошёл — навык заменяет старую версию (та уходит в .versions),
регистрируется в процедурной памяти и дальше находится по смыслу. Не прошёл — Джарвис получает ошибку и чинит.
"""

from __future__ import annotations

import ast
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from cogmem.memory import CognitiveMemory
from jarvis.workshop import Workshop

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
LOCKS = {"money", "message", "delete", "relative_device"}
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([a-z][a-z0-9_]*)", re.MULTILINE)

TEST_RUNNER = """
import importlib, sys, traceback
sys.dont_write_bytecode = True
mod = importlib.import_module("{name}.tests.test_skill")
n = fails = 0
for k in sorted(dir(mod)):
    f = getattr(mod, k)
    if k.startswith("test_") and callable(f):
        n += 1
        try:
            f()
            print("OK", k)
        except Exception:
            fails += 1
            print("FAIL", k)
            traceback.print_exc()
print("RESULT", n, fails)
sys.exit(1 if fails or n == 0 else 0)
"""


@dataclass
class SkillInfo:
    name: str
    description: str
    locks: list[str]
    path: Path


def _frontmatter(md: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---", md, re.DOTALL)
    out: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    return out


def _parse_locks(v: str) -> list[str]:
    return [x for x in re.findall(r"[a-z_]+", v or "") if x in LOCKS]


class SkillBank:
    def __init__(self, memory: CognitiveMemory, workshop: Workshop, root: str | Path = "data/skills"):
        self.memory = memory
        self.ws = workshop
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- чтение ---
    def get(self, name: str) -> SkillInfo | None:
        p = self.root / name / "SKILL.md"
        if not NAME_RE.match(name) or not p.exists():
            return None
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        return SkillInfo(name, fm.get("description", ""), _parse_locks(fm.get("locks", "")), p.parent)

    def all(self) -> list[SkillInfo]:
        return [s for s in (self.get(p.name) for p in sorted(self.root.iterdir()) if p.is_dir()) if s]

    def read(self, name: str) -> str:
        s = self.get(name)
        if s is None:
            return f"Навыка «{name}» нет."
        parts = [(s.path / "SKILL.md").read_text(encoding="utf-8")]
        code = (s.path / "__init__.py").read_text(encoding="utf-8")
        parts.append("Код (__init__.py):\n" + (code if len(code) < 8000 else code[:8000] + "\n…"))
        mem = s.path / ".memory.md"
        if mem.exists():
            parts.append("Заметки опыта:\n" + mem.read_text(encoding="utf-8")[-3000:])
        return "\n\n".join(parts)

    def search(self, viewer: str, query: str) -> str:
        found = self.memory.procedures.relevant(viewer, query, k=6, min_sim=0.0)
        if not found:
            names = ", ".join(s.name for s in self.all()) or "пока нет"
            return f"Похожих навыков не нашёл. Все навыки: {names}."
        return "\n".join(found)

    @staticmethod
    def imported(code: str) -> set[str]:
        """Имена модулей верхнего уровня, которые код импортирует (AST; для не-Python — по словам)."""
        names: set[str] = set()
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            return set(IMPORT_RE.findall(code)) | set(re.findall(r"\b([a-z][a-z0-9_]{1,40})\b", code))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                fn = node.func
                fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if fname in ("import_module", "__import__"):
                    names.add(node.args[0].value.split(".")[0])
        return names

    def used_in_code(self, code: str) -> set[str]:
        """Навыки, которыми код пользуется — прямо или через другие навыки (транзитивно)."""
        names = {s.name for s in self.all()}
        found: set[str] = set()
        todo = [code]
        while todo:
            text = todo.pop()
            direct = self.imported(text) & names
            # Навык с замком упомянут где угодно (python -m имя, строка для importlib…) — тоже считается.
            direct |= {n for n in names if n not in found and self._locked(n) and re.search(rf"\b{n}\b", text)}
            for n in direct - found:
                found.add(n)
                try:
                    todo.append((self.root / n / "__init__.py").read_text(encoding="utf-8"))
                except OSError:
                    pass
        return found

    def _locked(self, name: str) -> bool:
        s = self.get(name)
        return bool(s and s.locks)

    def locks_in_code(self, code: str) -> dict[str, list[str]]:
        """Какие навыки использует код (в т.ч. через другие навыки) и какие у них замки."""
        out = {}
        for name in self.used_in_code(code):
            s = self.get(name)
            if s is not None:
                out[name] = s.locks
        return out

    def code_of(self, names) -> str:
        """Код навыков (для поиска упомянутых в них секретов)."""
        parts = []
        for n in sorted(names):
            try:
                parts.append((self.root / n / "__init__.py").read_text(encoding="utf-8"))
            except OSError:
                pass
        return "\n".join(parts)

    # --- запись ---
    def note(self, name: str, text: str) -> str:
        s = self.get(name)
        if s is None:
            return f"Навыка «{name}» нет."
        stamp = time.strftime("%Y-%m-%d", time.gmtime(self.memory.ctx.clock.now()))
        with open(s.path / ".memory.md", "a", encoding="utf-8") as f:
            f.write(f"- {stamp}: {text.strip()}\n")
        return "Заметка добавлена."

    def create(self, name: str, *, description: str, instructions: str, code: str, tests: str,
               locks: list[str] | None = None) -> tuple[bool, str]:
        """Создать или обновить навык. Принимается только если тесты прошли."""
        if not NAME_RE.match(name):
            return False, "Имя навыка: латиница, цифры, «_», начинается с буквы (например btc_price)."
        if "def test_" not in tests:
            return False, "Нужны тесты: хотя бы одна функция test_… с проверками assert."
        locks = set(locks or []) & LOCKS
        kept = []
        old = self.get(name)
        if old is not None and set(old.locks) - locks:
            # Замок навыка не снимается обновлением: иначе любой текст мог бы «переписать» платёжный навык без замка.
            kept = sorted(set(old.locks) - locks)
            locks |= set(old.locks)
        # Навык, который пользуется навыком с замком, наследует его замки.
        for dep, dep_locks in self.locks_in_code(code).items():
            if dep != name:
                locks |= set(dep_locks)
        locks = sorted(locks)
        skill_md = (f"---\nname: {name}\ndescription: {description.strip()}\nlocks: [{', '.join(locks)}]\n---\n\n"
                    f"{instructions.strip()}\n")
        files = {
            f"{name}/__init__.py": code.encode(),
            f"{name}/SKILL.md": skill_md.encode(),
            f"{name}/tests/__init__.py": b"",
            f"{name}/tests/test_skill.py": tests.encode(),
        }
        res = self.ws.run(TEST_RUNNER.format(name=name), files=files, timeout=300, keep=False)
        if not res.ok:
            return False, "Тесты не прошли — навык не принят. Исправь и попробуй снова.\n" + res.summary(4000)

        # Принят: старую версию — в архив, новую — на место.
        dst = self.root / name
        if dst.exists():
            vdir = self.root / ".versions" / name / str(int(time.time()))
            vdir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(dst, vdir)
        staging = self.root / ".staging" / name
        shutil.rmtree(staging, ignore_errors=True)
        for rel, data in files.items():
            p = self.root / ".staging" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        mem_file = dst / ".memory.md"
        if mem_file.exists():
            shutil.copy2(mem_file, staging / ".memory.md")  # опыт сохраняем при обновлении
        shutil.rmtree(dst, ignore_errors=True)
        staging.replace(dst)
        self.memory.procedures.save(
            None, name, description,
            [f"навык {name}: {description} — в run_code: import {name}" + (f"; замки: {', '.join(locks)}" if locks else "")],
            visibility="family", actor="brain")
        note = (f"\nЗамки {', '.join(kept)} сохранены: снять замок с навыка обновлением нельзя." if kept else "")
        return True, f"Навык «{name}» принят (тесты прошли).{note}\n{res.stdout[-800:]}"

    def outcome(self, name: str, success: bool) -> None:
        row = self.memory.ctx.db.one("SELECT id FROM procedures WHERE name=? AND person_id IS NULL", (name,))
        if row:
            self.memory.procedures.outcome(row["id"], success)
