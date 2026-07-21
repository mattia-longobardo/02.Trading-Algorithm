"""Nodo debate (LLM): per candidato, bull vs bear per debate_rounds round
(loop interno al nodo, una chiamata per intervento), poi giudice.

Default AVOID: se l'output del giudice è malformato, se la chiamata fallisce o
se il caso bull non è nettamente più forte (istruzione esplicita al giudice).
"""

from __future__ import annotations

import logging

from etoro_bot.domain import DebateDecision, DebateVerdict
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.llm import extract_json
from etoro_bot.graph.nodes.common import llm_config, resolve_llm, system_blocks
from etoro_bot.graph.state import BotState

logger = logging.getLogger(__name__)


def debate(state: BotState, deps: GraphDeps) -> dict:
    reports_by_symbol: dict[str, list[dict]] = {}
    for report in state.get("analyst_reports") or []:
        reports_by_symbol.setdefault(report["symbol"], []).append(report)

    rounds = int(deps.settings.get("debate_rounds", 2))
    llm = resolve_llm(deps)
    model, max_tokens = llm_config(deps)
    system = system_blocks(deps)

    verdicts: list[DebateVerdict] = []
    errors: list[str] = []
    for cand in state.get("candidates") or []:
        symbol = cand["symbol"]
        reports = reports_by_symbol.get(symbol)
        if not reports:
            continue  # nessun report: niente dibattito, niente trade
        reports_text = "\n".join(
            f"- [{r['analyst']}] score {r['score']:+.2f}: {r['summary']}" for r in reports
        )
        transcript: list[dict] = []
        try:
            for rnd in range(1, rounds + 1):
                for role, label in (("bull", "INTERVENTO BULL"), ("bear", "INTERVENTO BEAR")):
                    prompt = (
                        f"{label} — dibattito su {symbol} (round {rnd}/{rounds}).\n"
                        f"Report analisti:\n{reports_text}\n"
                        f"Dibattito finora:\n{_transcript_text(transcript) or '(inizio)'}\n"
                        f"Argomenta in modo conciso (max 80 parole) il caso "
                        f"{'rialzista' if role == 'bull' else 'ribassista'} su {symbol}."
                    )
                    text = llm(
                        system_blocks=system, user_prompt=prompt,
                        model=model, max_tokens=max_tokens,
                    )
                    transcript.append({"role": role, "round": rnd, "text": text})

            judge_prompt = (
                f"Sei il GIUDICE del dibattito su {symbol}.\n"
                f"Report analisti:\n{reports_text}\n"
                f"Dibattito:\n{_transcript_text(transcript)}\n\n"
                "Decidi con prudenza: scegli open_long SOLO se il caso bull è nettamente "
                "più forte di quello bear; close solo per liquidare una posizione "
                "esistente; in ogni altro caso avoid.\n"
                'Rispondi SOLO con JSON: {"decision": "open_long|close|avoid", '
                '"conviction": <float 0..1>, "rationale": "..."}'
            )
            raw = llm(
                system_blocks=system, user_prompt=judge_prompt,
                model=model, max_tokens=max_tokens,
            )
            verdicts.append(_parse_judgement(symbol, raw, transcript))
        except Exception as exc:
            logger.warning("debate su %s fallito: default avoid (%s)", symbol, exc)
            errors.append(f"debate {symbol}: {exc}")
            verdicts.append(_avoid(symbol, f"debate fallito: {exc}", transcript))

    update: dict = {"verdicts": [v.model_dump(mode="json") for v in verdicts]}
    if errors:
        update["errors"] = errors
    return update


def _transcript_text(transcript: list[dict]) -> str:
    return "\n".join(f"[{t['role']} r{t['round']}] {t['text']}" for t in transcript)


def _avoid(symbol: str, rationale: str, transcript: list[dict]) -> DebateVerdict:
    return DebateVerdict(
        symbol=symbol,
        decision=DebateDecision.AVOID,
        conviction=0.0,
        rationale=rationale,
        transcript=transcript,
    )


def _parse_judgement(symbol: str, raw: str, transcript: list[dict]) -> DebateVerdict:
    full_transcript = transcript + [{"role": "judge", "round": 0, "text": raw}]
    try:
        data = extract_json(raw)
        decision = DebateDecision(str(data["decision"]))
        conviction = min(max(float(data.get("conviction", 0.0)), 0.0), 1.0)
        return DebateVerdict(
            symbol=symbol,
            decision=decision,
            conviction=conviction,
            rationale=str(data.get("rationale", "")),
            transcript=full_transcript,
        )
    except Exception:
        return _avoid(symbol, "output del giudice malformato: default avoid", full_transcript)
