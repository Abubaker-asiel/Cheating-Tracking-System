"""Event-level evaluation against independent ground truth.

Matching is one-to-one, per session and behaviour, on temporal IoU of intervals padded
by `pad` seconds (annotators disagree about exact boundaries). Seat identity is not
part of the match; add a seat column to your labels and extend match() if you need it.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from .rules import BEHAVIORS

nan = float("nan")


# --------------------------------------------------------------- loading
def load_gt(path: str | Path) -> list:
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({"session": r["session"].strip(), "behavior": r["behavior"].strip(),
                         "t_start": float(r["t_start"]), "t_end": float(r["t_end"]),
                         "notes": r.get("notes", "")})
    bad = [r for r in rows if r["behavior"] not in BEHAVIORS]
    if bad:
        raise ValueError(f"unknown behavior {bad[0]['behavior']!r}; expected one of {BEHAVIORS}")
    return rows


# --------------------------------------------------------------- matching
def _iv(e: dict, pad: float) -> tuple:
    end = e["t_end"] if e.get("t_end") is not None else e["t_start"]
    return e["t_start"] - pad, end + pad


def temporal_iou(a: tuple, b: tuple) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def match(gt: list, pred: list, iou_thr: float = 0.3, pad: float = 0.5):
    pairs = []
    for i, g in enumerate(gt):
        for j, p in enumerate(pred):
            iou = temporal_iou(_iv(g, pad), _iv(p, pad))
            if iou >= iou_thr:
                pairs.append((iou, i, j))
    pairs.sort(reverse=True)
    used_g, used_p, matches = set(), set(), []
    for iou, i, j in pairs:
        if i in used_g or j in used_p:
            continue
        used_g.add(i); used_p.add(j); matches.append((i, j, iou))
    fn = [i for i in range(len(gt)) if i not in used_g]
    fp = [j for j in range(len(pred)) if j not in used_p]
    return matches, fn, fp


# --------------------------------------------------------------- metrics
def _metrics(counts: dict, sessions: list, behaviors: list, hours: dict) -> dict:
    tp = sum(counts[(s, b)][0] for s in sessions for b in behaviors)
    fp = sum(counts[(s, b)][1] for s in sessions for b in behaviors)
    fn = sum(counts[(s, b)][2] for s in sessions for b in behaviors)
    h = sum(hours[s] for s in sessions)
    p = tp / (tp + fp) if tp + fp else nan
    r = tp / (tp + fn) if tp + fn else nan
    f1 = 2 * p * r / (p + r) if tp and p == p and r == r and p + r else (0.0 if tp + fp + fn else nan)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1,
            "false_alerts_per_hour": fp / h if h else nan, "hours": h}


def evaluate(gt: list, pred: list, durations: dict, iou_thr: float = 0.3, pad: float = 0.5,
             behaviors=BEHAVIORS, n_boot: int = 1000, seed: int = 0) -> dict:
    sessions = sorted({g["session"] for g in gt})
    missing = [s for s in sessions if s not in durations]
    if missing:
        raise ValueError(f"no processed run for sessions: {missing}")
    hours = {s: durations[s] / 3600 for s in sessions}
    counts, misses, false_alarms = {}, [], []
    for s in sessions:
        for b in behaviors:
            g = [x for x in gt if x["session"] == s and x["behavior"] == b]
            p = [x for x in pred if x["session"] == s and x["behavior"] == b]
            _, fn, fp = match(g, p, iou_thr, pad)
            counts[(s, b)] = (len(g) - len(fn), len(fp), len(fn))
            misses += [dict(g[i]) for i in fn]
            false_alarms += [p[j] for j in fp]
    out = {"iou_thr": iou_thr, "pad": pad, "sessions": sessions, "behaviors": list(behaviors),
           "overall": _metrics(counts, sessions, list(behaviors), hours),
           "per_behavior": {b: _metrics(counts, sessions, [b], hours) for b in behaviors},
           "per_session": {s: _metrics(counts, [s], list(behaviors), hours) for s in sessions},
           "misses": sorted(misses, key=lambda e: e["t_start"] - e["t_end"]),  # longest first
           "false_alarms": sorted(false_alarms, key=lambda e: -(e.get("peak_conf") or 0))}
    out["ci95"] = _bootstrap(counts, sessions, list(behaviors), hours, n_boot, seed)
    return out


def _bootstrap(counts, sessions, behaviors, hours, n, seed):
    """Resample whole sessions: the session, not the event, is the independent unit."""
    if len(sessions) < 2:
        return None
    rng = np.random.default_rng(seed)
    keys = ("precision", "recall", "f1", "false_alerts_per_hour")
    series = {b: {k: [] for k in keys} for b in ["overall", *behaviors]}
    for _ in range(n):
        samp = [sessions[i] for i in rng.integers(0, len(sessions), len(sessions))]
        for name in series:
            m = _metrics(counts, samp, behaviors if name == "overall" else [name], hours)
            for k in keys:
                series[name][k].append(m[k])
    ci = {}
    for name, d in series.items():
        ci[name] = {}
        for k, v in d.items():
            a = np.array(v, dtype=float)
            ci[name][k] = (None, None) if np.isnan(a).all() else (
                float(np.nanpercentile(a, 2.5)), float(np.nanpercentile(a, 97.5)))
    return ci



# --------------------------------------------------------------- agreement
def to_bins(events: list, session: str, behavior: str, duration: float, bin_s: float = 1.0) -> np.ndarray:
    n = int(np.ceil(duration / bin_s))
    arr = np.zeros(n, dtype=bool)
    for e in events:
        if e["session"] == session and e["behavior"] == behavior:
            end = e["t_end"] if e.get("t_end") is not None else e["t_start"]
            arr[int(max(0, e["t_start"] // bin_s)):int(min(n, end // bin_s + 1))] = True
    return arr


def cohen_kappa(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) == 0:
        return nan
    po = float(np.mean(a == b))
    pa, pb = float(np.mean(a)), float(np.mean(b))
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


def agreement(ev_a: list, ev_b: list, durations: dict, sessions: list, behaviors=BEHAVIORS, bin_s: float = 1.0) -> dict:
    """Cohen's kappa on 1 s bins, pooled over sessions, plus per behaviour."""
    out, all_a, all_b = {}, [], []
    for b in behaviors:
        xa = [to_bins(ev_a, s, b, durations[s], bin_s) for s in sessions]
        xb = [to_bins(ev_b, s, b, durations[s], bin_s) for s in sessions]
        a, c = np.concatenate(xa), np.concatenate(xb)
        out[b] = cohen_kappa(a, c)
        all_a.append(a); all_b.append(c)
    out["overall"] = cohen_kappa(np.concatenate(all_a), np.concatenate(all_b))
    return out


# --------------------------------------------------------------- reviewer log
def reviewer_stats(events: list) -> dict:
    c = defaultdict(int)
    for e in events:
        c[e["review_status"]] += 1
    reviewed = c["confirmed"] + c["dismissed"]
    return {"pending": c["pending"], "confirmed": c["confirmed"], "dismissed": c["dismissed"],
            "dismissal_rate": c["dismissed"] / reviewed if reviewed else nan}


# --------------------------------------------------------------- report
def _f(x, nd=2):
    return "n/a" if x is None or x != x else f"{x:.{nd}f}"


def _ci(ci, name, key):
    if not ci:
        return ""
    lo, hi = ci[name][key]
    return "" if lo is None else f" [{lo:.2f}, {hi:.2f}]"


def render_report(results: dict, reviewer: dict, kappas: dict, worst_n: int = 10) -> str:
    """results: {tag: evaluate() output}. kappas: {label: agreement() output}."""
    L = ["# Invigil evaluation report", ""]
    first = next(iter(results.values()))
    L += [f"Sessions: {', '.join(first['sessions'])}  ",
          f"Matching: temporal IoU >= {first['iou_thr']} on intervals padded by {first['pad']} s.  ",
          "Intervals in brackets are 95% bootstrap CIs over sessions "
          "(only shown with 2+ sessions; with a handful of sessions they will be wide, and that is the honest answer).", ""]
    L += ["## Overall", "", "| run | precision | recall | F1 | false alerts / hour | TP | FP | FN |", "|---|---|---|---|---|---|---|---|"]
    for tag, r in results.items():
        o = r["overall"]
        L.append(f"| {tag} | {_f(o['precision'])}{_ci(r['ci95'],'overall','precision')} | "
                 f"{_f(o['recall'])}{_ci(r['ci95'],'overall','recall')} | {_f(o['f1'])}{_ci(r['ci95'],'overall','f1')} | "
                 f"{_f(o['false_alerts_per_hour'])}{_ci(r['ci95'],'overall','false_alerts_per_hour')} | {o['tp']} | {o['fp']} | {o['fn']} |")
    L += ["", "## Per behavior", "", "| run | behavior | precision | recall | F1 | FA/h | TP | FP | FN |", "|---|---|---|---|---|---|---|---|---|"]
    for tag, r in results.items():
        for b, m in r["per_behavior"].items():
            L.append(f"| {tag} | {b} | {_f(m['precision'])} | {_f(m['recall'])} | {_f(m['f1'])} | {_f(m['false_alerts_per_hour'])} | {m['tp']} | {m['fp']} | {m['fn']} |")
    L += ["", "## Per session", "", "| run | session | precision | recall | FA/h | TP | FP | FN |", "|---|---|---|---|---|---|---|---|"]
    for tag, r in results.items():
        for s, m in r["per_session"].items():
            L.append(f"| {tag} | {s} | {_f(m['precision'])} | {_f(m['recall'])} | {_f(m['false_alerts_per_hour'])} | {m['tp']} | {m['fp']} | {m['fn']} |")
    if kappas:
        L += ["", "## Agreement (Cohen's kappa, 1 s bins)", "", "| pair | overall | " + " | ".join(first["behaviors"]) + " |",
              "|---|---|" + "---|" * len(first["behaviors"])]
        for label, k in kappas.items():
            L.append(f"| {label} | {_f(k['overall'])} | " + " | ".join(_f(k[b]) for b in first["behaviors"]) + " |")
    L += ["", "## Reviewer log (alert history)", "",
          f"pending {reviewer['pending']}, confirmed {reviewer['confirmed']}, dismissed {reviewer['dismissed']}; "
          f"dismissal rate among reviewed: {_f(reviewer['dismissal_rate'])}. "
          "Dismissals are an independent estimate of the false-positive rate."]
    for tag, r in results.items():
        L += ["", f"## {tag}: {worst_n} longest misses", ""]
        L += [f"- {m['session']} {m['behavior']} {m['t_start']:.1f}-{m['t_end']:.1f}s {m.get('notes','')}" for m in r["misses"][:worst_n]] or ["- none"]
        L += ["", f"## {tag}: {worst_n} most confident false alarms", ""]
        L += [f"- {e['session']} {e['behavior']} id{e.get('track_id')} {e['t_start']:.1f}s conf {_f(e.get('peak_conf'))} "
              f"{e.get('best_shot') or e.get('onset_shot') or ''}" for e in r["false_alarms"][:worst_n]] or ["- none"]
    return "\n".join(L) + "\n"


def write_outputs(out_dir: str | Path, results: dict, report_md: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(report_md)
    slim = {t: {k: v for k, v in r.items() if k not in ("misses", "false_alarms")} for t, r in results.items()}
    (out / "metrics.json").write_text(json.dumps(slim, indent=2, default=str))
