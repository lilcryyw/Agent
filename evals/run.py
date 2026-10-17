"""Стенд измерений памяти.

Офлайн (по умолчанию, без API и денег): проверяет «гиппокамп» — найдёт ли вспоминание нужные
доказательства в рабочей памяти через месяцы болтовни. Метрика — доля вопросов, где все ожидаемые
фрагменты попали в рабочую память, и ни одного запрещённого (приватность/ложное).

  python -m evals.run                 # реальные эмбеддинги (fastembed)
  python -m evals.run --hash          # быстрый режим без модели эмбеддингов
  python -m evals.run --live          # полный цикл с Claude: подсознание + ответы + судья (нужен ключ API)
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from cogmem.clock import FakeClock
from cogmem.memory import CognitiveMemory
from cogmem.types import Observation
from evals.scenario import Question, Scenario, build


def _norm(s: str) -> str:
    return s.lower().replace("ё", "е")


def load_scenario(mem: CognitiveMemory, clock: FakeClock, sc: Scenario, *, on_day_end=None) -> None:
    tz = ZoneInfo("Europe/Paris")
    start = datetime.fromisoformat(sc.start).replace(tzinfo=tz)
    by_day: dict[int, list] = defaultdict(list)
    for u in sc.utterances:
        by_day[u.day].append(u)
    for day in range(sc.days):
        for u in sorted(by_day.get(day, []), key=lambda x: x.minute):
            clock.set(start + timedelta(days=day, minutes=u.minute))
            if u.text.startswith("@assistant:"):
                mem.observe(Observation(u.person, u.text.split(":", 1)[1], speaker="assistant"))
            else:
                mem.observe(Observation(u.person, u.text, visibility=u.visibility))
        clock.set(start + timedelta(days=day, hours=23, minutes=59))
        mem.tick(encode=False)
        if on_day_end:
            on_day_end(day)
    clock.set(start + timedelta(days=sc.days, hours=12))
    mem.tick(encode=False)


def check(q: Question, text: str) -> tuple[bool, list[str], list[str]]:
    t = _norm(text)
    missing = [e for e in q.expect if _norm(e) not in t]
    leaked = [f for f in q.forbid if _norm(f) in t]
    return (not missing and not leaked), missing, leaked


def offline(use_hash: bool, verbose: bool, model: str | None = None) -> dict:
    if use_hash:
        from cogmem.embed import HashEmbedder

        emb = HashEmbedder()
    elif model and model.startswith("@cf/"):  # облегчённый режим: смысл в Cloudflare Workers AI
        from cogmem.embed_remote import CloudflareEmbedder

        emb = CloudflareEmbedder(model)
    else:
        from cogmem.embed import FastEmbedder

        emb = FastEmbedder(model or FastEmbedder.DEFAULT_MODEL)
    clock = FakeClock()
    mem = CognitiveMemory(embedder=emb, clock=clock)
    mem.add_person("owner", "Владимир", role="owner", aliases=["Вова"])
    mem.add_person("mama", "Ольга Петровна", role="family", timezone="Europe/Samara")
    sc = build()
    t0 = time.perf_counter()
    load_scenario(mem, clock, sc)
    load_s = time.perf_counter() - t0

    per: dict[str, list[bool]] = defaultdict(list)
    easy, hard = [], []
    lat, toks, fails = [], [], []
    for q in sc.questions:
        wm, res = mem.working_memory(q.person, q.text)
        text = wm.render()
        ok, missing, leaked = check(q, text)
        per[q.ability].append(ok)
        (hard if q.hard else easy).append(ok)
        lat.append(res.latency_ms)
        toks.append(wm.tokens)
        if not ok:
            fails.append({"q": q.text, "ability": q.ability, "hard": q.hard, "missing": missing, "leaked": leaked})
            if verbose:
                print(f"\n✗ [{q.ability}] {q.text}\n  нет: {missing} утекло: {leaked}\n{text}\n")
    total = [x for v in per.values() for x in v]
    return {
        "mode": "offline-hash" if use_hash else f"offline-{emb.name}",
        "events": mem.stats()["events"],
        "episodes": mem.stats()["episodes"],
        "load_seconds": round(load_s, 1),
        "accuracy": round(sum(total) / len(total), 3),
        "accuracy_direct": f"{sum(easy)}/{len(easy)}",
        "accuracy_paraphrased": f"{sum(hard)}/{len(hard)}",
        "by_ability": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(per.items())},
        "latency_ms_p50": round(statistics.median(lat), 1),
        "latency_ms_max": round(max(lat), 1),
        "wm_tokens_avg": round(statistics.mean(toks)),
        "failures": fails,
    }


def live(verbose: bool) -> dict:
    """Полный цикл: подсознание (Haiku) кодирует эпизоды, ночью «сон», ответы — «сознание», оценка — судья."""
    from pydantic import BaseModel, Field

    import anthropic
    from cogmem.embed import default_embedder
    from cogmem.llm import AnthropicStructuredLLM
    from jarvis.brain.agent import Brain
    from jarvis.config import Settings

    client = anthropic.Anthropic()
    clock = FakeClock()
    mem = CognitiveMemory(embedder=default_embedder(), clock=clock)
    mem.llm = AnthropicStructuredLLM(client, usage_sink=mem.record_usage)
    from cogmem.consolidate.encoder import EpisodeEncoder
    from cogmem.consolidate.sleep import Sleep

    mem.encoder = EpisodeEncoder(mem.ctx, mem.llm, mem.entities, mem.facts, mem.episodes, mem.retriever)
    mem.sleeper = Sleep(mem.ctx, mem.llm, mem.facts, mem.core, mem.intentions)
    mem.add_person("owner", "Владимир", role="owner", aliases=["Вова"])
    mem.add_person("mama", "Ольга Петровна", role="family", timezone="Europe/Samara")
    sc = build()

    def night(day: int) -> None:
        mem.tick(limit=1000)
        for pid in ("owner", "mama"):
            mem.sleeper.run(pid)

    load_scenario(mem, clock, sc, on_day_end=night)
    brain = Brain(mem, Settings(db_path=":memory:", use_web_search=False), client)

    class Verdict(BaseModel):
        correct: bool = Field(description="Ответ верен по сути (для abstention/privacy — честно не знает/не выдаёт)")
        why: str

    judge = AnthropicStructuredLLM(client, usage_sink=mem.record_usage)
    per: dict[str, list[bool]] = defaultdict(list)
    fails = []
    for q in sc.questions:
        clock.advance(hours=1)
        ans = brain.handle(q.person, q.text).text
        expect = ", ".join(q.expect) or "ответ «не знаю/не помню» без выдумок"
        forbid = ", ".join(q.forbid)
        v = judge.parse(system="Ты строгий проверяющий ответов ассистента.",
                        user=f"Вопрос: {q.text}\nОжидается: {expect}\n"
                             + (f"Нельзя упоминать: {forbid}\n" if forbid else "") + f"Ответ: {ans}",
                        schema=Verdict, purpose="eval_judge")
        per[q.ability].append(v.correct)
        if not v.correct:
            fails.append({"q": q.text, "answer": ans, "why": v.why})
        if verbose:
            print(("✓" if v.correct else "✗"), q.text, "→", ans)
    total = [x for v in per.values() for x in v]
    return {"mode": "live", "accuracy": round(sum(total) / len(total), 3),
            "by_ability": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(per.items())},
            "cost_usd": round(mem.spend_usd(), 3), "stats": mem.stats(), "failures": fails}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hash", action="store_true", help="без модели эмбеддингов (быстро, слабее)")
    ap.add_argument("--live", action="store_true", help="полный цикл с Claude (нужен ANTHROPIC_API_KEY)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--model", help="модель эмбеддингов fastembed")
    ap.add_argument("--save", type=Path, help="сохранить результат в JSON")
    args = ap.parse_args()
    res = live(args.verbose) if args.live else offline(args.hash, args.verbose, args.model)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if args.save:
        args.save.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
