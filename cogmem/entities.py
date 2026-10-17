"""Сущности-схемы и словарь имён/прозвищ.

Сущность — «понятие» (человек, место, устройство...). На неё указывают эпизоды и факты —
как индексы гиппокампа указывают на представления в коре. Через сущности работает
ассоциативное вспоминание (распространение активации по графу).
"""

from __future__ import annotations

from dataclasses import dataclass

from cogmem.context import Ctx
from cogmem.govern.access import can_see
from cogmem.store import to_blob
from cogmem.text import ru

ENTITY_KINDS = {"person", "place", "device", "org", "object", "topic", "pet", "self", "other"}

# Родственные слова: «мама» у каждого члена семьи своя — такие прозвища никогда не бывают общими (scope='').
_KIN_WORDS = """мама мать мамочка мамуля маман матушка папа отец папочка папуля батя бабушка баба бабуля бабуленька
дедушка дед деда дедуля сын сынок сыночек дочь дочка доченька жена супруга муж супруг брат братик братишка сестра
сестрёнка сестричка тётя тетя тётка дядя внук внучка правнук правнучка свекровь свёкор свекор тёща теща тесть
зять невестка сноха племянник племянница кузен кузина крёстная крестная крёстный крестный мачеха отчим пасынок
падчерица родители предки любимая любимый милый милая""".split()
_KIN_FILLER = "мой моя моё мое мои наш наша наше наши твой твоя старший старшая младший младшая родной родная".split()
_KIN = {ru.stem(ru.normalize(w)) for w in _KIN_WORDS}
_KIN_FILL = {ru.stem(ru.normalize(w)) for w in _KIN_FILLER}


def is_kinship_norm(alias_norm: str) -> bool:
    """Нормализованное прозвище состоит только из родственных слов («мам», «мо мам», «стар брат»)?"""
    toks = alias_norm.split()
    core = [t for t in toks if t not in _KIN_FILL]
    return bool(core) and all(t in _KIN for t in core)


def is_kinship(alias: str) -> bool:
    return is_kinship_norm(ru.alias_norm(alias))


@dataclass
class Entity:
    id: int
    kind: str
    name: str
    card: str
    owner_person: str | None
    visibility: str
    importance: float


class EntityStore:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self._alias_cache: dict[str, list[tuple[int, str]]] | None = None

    # --- чтение ---
    def get(self, entity_id: int) -> Entity | None:
        r = self.ctx.db.one("SELECT * FROM entities WHERE id=?", (entity_id,))
        if r is None:
            return None
        while r["merged_into"]:
            r = self.ctx.db.one("SELECT * FROM entities WHERE id=?", (r["merged_into"],))
        return Entity(r["id"], r["kind"], r["name"], r["card"], r["owner_person"], r["visibility"], r["importance"])

    def _aliases(self) -> dict[str, list[tuple[int, str]]]:
        if self._alias_cache is None:
            cache: dict[str, list[tuple[int, str]]] = {}
            for r in self.ctx.db.query(
                "SELECT a.alias_norm, a.entity_id, a.person_scope FROM aliases a "
                "JOIN entities e ON e.id=a.entity_id WHERE e.merged_into IS NULL"
            ):
                cache.setdefault(r["alias_norm"], []).append((r["entity_id"], r["person_scope"]))
            self._alias_cache = cache
        return self._alias_cache

    def _visible(self, entity_id: int, viewer: str) -> bool:
        r = self.ctx.db.one("SELECT owner_person, visibility FROM entities WHERE id=?", (entity_id,))
        return r is not None and can_see(viewer, r["owner_person"], r["visibility"])

    def resolve(self, name: str, viewer: str) -> int | None:
        """Найти сущность по имени/прозвищу с учётом того, кто говорит («мама» у каждого своя)."""
        norm = ru.alias_norm(name)
        if not norm:
            return None
        cands = self._aliases().get(norm, [])
        scoped = [eid for eid, scope in cands if scope == viewer and self._visible(eid, viewer)]
        if scoped:
            return scoped[0]
        glob = [eid for eid, scope in cands if scope == "" and self._visible(eid, viewer)]
        return glob[0] if glob else None

    def mentions(self, text: str, viewer: str) -> list[int]:
        """Все сущности, упомянутые в тексте (по n-граммам основ слов, до 3 слов)."""
        toks = [ru.stem(w) for w in ru.words(text)]
        found: list[int] = []
        aliases = self._aliases()
        for n in (3, 2, 1):
            for i in range(len(toks) - n + 1):
                key = " ".join(toks[i : i + n])
                for eid, scope in aliases.get(key, []):
                    if scope in ("", viewer) and eid not in found and self._visible(eid, viewer):
                        found.append(eid)
        return found

    # --- запись ---
    def create(self, name: str, *, kind: str = "other", owner: str | None, visibility: str = "private",
               aliases: list[str] | None = None, alias_scope: str = "", importance: float = 0.3,
               actor: str = "subconscious", reason: str = "") -> int:
        kind = kind if kind in ENTITY_KINDS else "other"
        now = self.ctx.clock.now()
        vec = self.ctx.embed1(name.strip())
        with self.ctx.db.tx():
            cur = self.ctx.db.execute(
                "INSERT INTO entities(kind, name, owner_person, visibility, importance, embedding, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (kind, name.strip(), owner, visibility, importance, to_blob(vec), now, now),
            )
            eid = cur.lastrowid
            # Родственное слово — прозвище только в речи того, чья это родня (иначе «мама» жены = мама мужа).
            kin_scope = alias_scope or owner or None
            self.add_alias(eid, name, scope=(kin_scope or "") if is_kinship(name) else "",
                           skip=is_kinship(name) and kin_scope is None)
            for a in aliases or []:
                self.add_alias(eid, a, scope=(kin_scope or "") if is_kinship(a) else alias_scope,
                               skip=is_kinship(a) and kin_scope is None)
            self.ctx.fts_add("entity", eid, name)
            self.ctx.trace("entity", eid, "created", now)
            self.ctx.audit.log(actor, "create", "entity", eid, after={"name": name, "kind": kind}, reason=reason)
        self.ctx.index.add("entity", eid, vec, owner=owner, visibility=visibility, ts=now)
        return eid

    def add_alias(self, entity_id: int, alias: str, scope: str = "", *, skip: bool = False) -> None:
        """Прозвище → сущность. Родственное слово без scope (чья это мама?) не регистрируется."""
        norm = ru.alias_norm(alias)
        if not norm or skip or (scope == "" and is_kinship_norm(norm)):
            return
        self.ctx.db.execute(
            "INSERT OR IGNORE INTO aliases(alias_norm, entity_id, person_scope) VALUES (?,?,?)", (norm, entity_id, scope)
        )
        self._alias_cache = None

    def get_or_create(self, name: str, *, viewer: str, kind: str = "other", aliases: list[str] | None = None,
                      visibility: str = "private", reason: str = "") -> int:
        eid = self.resolve(name, viewer)
        for a in aliases or []:
            if eid is None:
                eid = self.resolve(a, viewer)
        if eid is not None:
            for a in aliases or []:
                self.add_alias(eid, a, scope=viewer)
            return eid
        return self.create(name, kind=kind, owner=viewer, visibility=visibility, aliases=aliases,
                           alias_scope=viewer, reason=reason)

    def set_card(self, entity_id: int, card: str, *, actor: str, reason: str = "") -> None:
        old = self.ctx.db.one("SELECT card, name, owner_person, visibility FROM entities WHERE id=?", (entity_id,))
        if old is None or old["card"] == card:
            return
        vec = self.ctx.embed1(f"{old['name']}. {card}")
        now = self.ctx.clock.now()
        with self.ctx.db.tx():
            self.ctx.db.execute(
                "UPDATE entities SET card=?, embedding=?, updated_at=? WHERE id=?", (card, to_blob(vec), now, entity_id)
            )
            self.ctx.fts_add("entity", entity_id, f"{old['name']} {card}")
            self.ctx.audit.log(actor, "card", "entity", entity_id, before=old["card"], after=card, reason=reason)
        self.ctx.index.add("entity", entity_id, vec, owner=old["owner_person"], visibility=old["visibility"], ts=now)

    def merge(self, keep_id: int, drop_id: int, *, actor: str, reason: str = "") -> None:
        """Слить дубликаты сущностей (найдено при «сне»)."""
        if keep_id == drop_id:
            return
        with self.ctx.db.tx():
            self.ctx.db.execute("UPDATE entities SET merged_into=? WHERE id=?", (keep_id, drop_id))
            self.ctx.db.execute(
                "INSERT OR IGNORE INTO aliases(alias_norm, entity_id, person_scope) "
                "SELECT alias_norm, ?, person_scope FROM aliases WHERE entity_id=?", (keep_id, drop_id)
            )
            self.ctx.db.execute("UPDATE facts SET subject_id=? WHERE subject_id=?", (keep_id, drop_id))
            self.ctx.db.execute("UPDATE facts SET object_id=? WHERE object_id=?", (keep_id, drop_id))
            self.ctx.db.execute(
                "UPDATE OR IGNORE links SET dst_id=? WHERE dst_type='entity' AND dst_id=?", (keep_id, drop_id)
            )
            self.ctx.audit.log(actor, "merge", "entity", drop_id, after={"into": keep_id}, reason=reason)
        self.ctx.index.set_active("entity", drop_id, False)
        self._alias_cache = None
