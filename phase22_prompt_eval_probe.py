"""
PHASE 22 -- follow-up investigation (not one of the original 5 candidates).

Purpose
-------
Run 1 of the last phase22_profile_pipeline.py session showed
prompt_eval_duration = 31.87s for a 1614-token prompt, while Run 2 and
Run 3 processed the SAME 1614-token prompt in 0.36-0.37s. load_duration
was near-zero (0.006-0.011s) in all three runs, so this is NOT the
model-reload cost that keep_alive (candidate #2) already fixed -- it is
something else that only hit the very first fused-reasoning call.

Hypothesis being tested
------------------------
CPU-only inference (confirmed in model_config.py's MODEL SELECTION
RECORD: AMD Ryzen 5 5625U, 16GB RAM, no usable iGPU compute path).
Ollama's own "keep_alive" keeps the model handle resident, but the
model's weight file is memory-mapped from disk -- the OS still has to
have those pages resident in its own page cache for access to be fast.
If those pages get evicted (RAM pressure from Django/IDE/browser/etc.,
or simply not yet touched since the OS/machine was last used), the
FIRST forward pass that touches them pays real disk-read cost during
prompt evaluation, independent of whether Ollama itself ever "unloaded"
the model. That would explain a slow prompt_eval_duration on the first
call of a session even with load_duration ~0.

This script does not touch production code, the database, or any
Django model. It talks to Ollama directly, using the SAME endpoint,
model name and keep_alive setting as llm_service.py (imported, not
duplicated), with a synthetic filler prompt sized to roughly match the
~1614-token fused-reasoning prompt from Run 1. It runs a first call,
then repeats the identical prompt after several increasing idle gaps,
logging Ollama's full timing breakdown each time, plus a best-effort
snapshot of free system RAM before each call (psutil if installed,
Windows ctypes fallback, else reported as n/a -- never fails the run).

Usage:
    python phase22_prompt_eval_probe.py
    python phase22_prompt_eval_probe.py --gaps 0,60,180,300 --prompt-tokens 1600

No commit/push/deploy implied. Diagnostic only.
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime

# No Django settings needed -- model_config.py only imports os/requests,
# so this works from the repo root without touching manage.py/Django at
# all (even less invasive than phase22_profile_pipeline.py).
from ai_engine.services.model_config import (
    MODEL_NAME,
    OLLAMA_GENERATE_URL,
    OLLAMA_TIMEOUT_SECONDS,
    OLLAMA_KEEP_ALIVE,
)

import requests


def get_ollama_ps():
    """
    Best-effort `ollama ps` snapshot (shows which model(s) are
    currently resident and for how much longer, per Ollama's own
    accounting) -- read-only CLI call, never raises. Returns the raw
    text, or None if the `ollama` CLI isn't reachable from here.
    """
    try:
        result = subprocess.run(
            ["ollama", "ps"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (result.stdout or "").strip() or (result.stderr or "").strip()
    except Exception:
        return None


def get_free_ram_mb():
    """
    Best-effort free-RAM snapshot. Never raises -- returns None if no
    method is available, so the probe still runs on any machine.
    """
    try:
        import psutil
        return round(psutil.virtual_memory().available / (1024 * 1024))
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return round(stat.ullAvailPhys / (1024 * 1024))
        except Exception:
            pass

    return None


def build_filler_prompt(approx_tokens):
    """
    Synthetic filler prompt sized to roughly approx_tokens (rough
    heuristic: ~1.3 tokens per word for English-ish text). Content is
    meaningless on purpose -- this script only cares about timing, not
    output quality, and never inspects the generated JSON.
    """
    words_needed = max(10, int(approx_tokens / 1.3))
    filler = " ".join(["context"] * words_needed)
    return (
        "Ignore the repeated word below, it is padding to reach a "
        "target prompt length for a timing test. Respond with a tiny "
        "JSON object like {\"ok\": true}.\n\n" + filler
    )


def call_ollama(prompt, ns_to_s):
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": OLLAMA_KEEP_ALIVE,
        # Keep generation short on purpose -- this probe isolates
        # PROMPT evaluation cost, not output generation cost (that is
        # candidate #3, already being investigated separately).
        "options": {"num_predict": 16},
    }

    t0 = time.perf_counter()
    response = requests.post(
        OLLAMA_GENERATE_URL,
        json=payload,
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    wall = time.perf_counter() - t0
    response.raise_for_status()
    data = response.json()

    pe_count = data.get("prompt_eval_count")
    pe_dur = ns_to_s(data.get("prompt_eval_duration"))
    ev_count = data.get("eval_count")
    ev_dur = ns_to_s(data.get("eval_duration"))

    return {
        "wall_clock": wall,
        "total_duration": ns_to_s(data.get("total_duration")),
        "load_duration": ns_to_s(data.get("load_duration")),
        "prompt_eval_count": pe_count if pe_count is not None else "n/a",
        "prompt_eval_duration": pe_dur,
        "prompt_eval_tokens_per_sec": (
            round(pe_count / pe_dur, 1)
            if isinstance(pe_count, (int, float)) and pe_dur else None
        ),
        "eval_count": ev_count if ev_count is not None else "n/a",
        "eval_duration": ev_dur,
        "eval_tokens_per_sec": (
            round(ev_count / ev_dur, 1)
            if isinstance(ev_count, (int, float)) and ev_dur else None
        ),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Phase 22 follow-up: isolate the prompt_eval_duration "
        "spike seen on the first fused-reasoning call."
    )
    parser.add_argument(
        "--gaps",
        type=str,
        default="0,60,180",
        help="Comma-separated idle gaps in seconds before each repeat "
        "call (default: 0,60,180). Add 300 to also cross Ollama's own "
        "default 5-minute keep_alive boundary as a sanity check.",
    )
    parser.add_argument(
        "--prompt-tokens",
        type=int,
        default=1600,
        help="Approx prompt size in tokens, to roughly match the "
        "1614-token fused-reasoning prompt from Run 1 (default: 1600).",
    )
    args = parser.parse_args()

    gaps = [int(g.strip()) for g in args.gaps.split(",") if g.strip() != ""]
    ns_to_s = lambda ns: (ns / 1e9) if isinstance(ns, (int, float)) else None

    prompt = build_filler_prompt(args.prompt_tokens)

    print("PHASE 22 -- prompt_eval anomaly probe. Diagnostic only.")
    print("Talks to Ollama directly. No database writes. No production")
    print("code modified. No commit/push.")
    print(f"model={MODEL_NAME}  keep_alive={OLLAMA_KEEP_ALIVE}  "
          f"target_prompt_tokens={args.prompt_tokens}  gaps={gaps}\n")

    results = []

    print("--- Call 0 (baseline -- this should be the FIRST relevant")
    print("    request if you just restarted Ollama) ---")
    print("ollama ps BEFORE this call:")
    print(get_ollama_ps() or "  (ollama CLI not reachable from here -- n/a)")
    ram_before = get_free_ram_mb()
    ts_before = datetime.now().isoformat(timespec="seconds")
    r = call_ollama(prompt, ns_to_s)
    r["label"] = "call_0_baseline"
    r["gap_before_s"] = 0
    r["free_ram_mb_before"] = ram_before
    r["timestamp"] = ts_before
    results.append(r)
    print(_format_result(r))
    print("ollama ps AFTER this call:")
    print(get_ollama_ps() or "  (ollama CLI not reachable from here -- n/a)")

    for gap in gaps:
        print(f"\n--- Sleeping {gap}s before next call ---")
        time.sleep(gap)
        print(f"--- Call after {gap}s idle gap ---")
        ram_before = get_free_ram_mb()
        ts_before = datetime.now().isoformat(timespec="seconds")
        r = call_ollama(prompt, ns_to_s)
        r["label"] = f"call_after_{gap}s_gap"
        r["gap_before_s"] = gap
        r["free_ram_mb_before"] = ram_before
        r["timestamp"] = ts_before
        results.append(r)
        print(_format_result(r))

        # Immediate repeat right after, zero gap -- to confirm the
        # SECOND call after any gap is always fast (matches what we
        # already saw in Run 2/Run 3), isolating whether it is
        # specifically "first touch after idle" that is slow.
        print(f"--- Immediate repeat (0s gap) after the {gap}s-gap call ---")
        ram_before = get_free_ram_mb()
        ts_before = datetime.now().isoformat(timespec="seconds")
        r2 = call_ollama(prompt, ns_to_s)
        r2["label"] = f"immediate_repeat_after_{gap}s_gap"
        r2["gap_before_s"] = 0
        r2["free_ram_mb_before"] = ram_before
        r2["timestamp"] = ts_before
        results.append(r2)
        print(_format_result(r2))

    _print_summary(results)


def _format_result(r):
    ram = r["free_ram_mb_before"]
    ram_str = f"{ram} MB" if ram is not None else "n/a"
    pe_tps = r.get("prompt_eval_tokens_per_sec")
    ev_tps = r.get("eval_tokens_per_sec")
    return (
        f"  timestamp={r.get('timestamp', 'n/a')}  "
        f"free_ram_before={ram_str}  "
        f"total_duration={r['total_duration']}s  "
        f"load_duration={r['load_duration']}s  "
        f"prompt_eval_count={r['prompt_eval_count']}  "
        f"prompt_eval_duration={r['prompt_eval_duration']}s  "
        f"prompt_eval_tok/s={pe_tps if pe_tps is not None else 'n/a'}  "
        f"eval_count={r['eval_count']}  "
        f"eval_duration={r['eval_duration']}s  "
        f"eval_tok/s={ev_tps if ev_tps is not None else 'n/a'}"
    )


def _print_summary(results):
    print("\n" + "=" * 70)
    print("SUMMARY -- prompt_eval_duration by call, in order")
    print("=" * 70)
    header = (
        f"{'label':<32} {'gap_s':>6} {'free_ram_mb':>12} "
        f"{'load_dur':>10} {'prompt_eval_dur':>16}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        ram = r["free_ram_mb_before"]
        ram_str = f"{ram}" if ram is not None else "n/a"
        load_d = r["load_duration"]
        pe_d = r["prompt_eval_duration"]
        print(
            f"{r['label']:<32} {r['gap_before_s']:>6} {ram_str:>12} "
            f"{(f'{load_d:.3f}' if load_d is not None else 'n/a'):>10} "
            f"{(f'{pe_d:.3f}' if pe_d is not None else 'n/a'):>16}"
        )

    print(
        "\nRead this as evidence, not a verdict: if prompt_eval_duration "
        "is only high on call_0 / calls right after a long gap, and the "
        "immediate repeats are consistently fast regardless of free RAM, "
        "that points at a one-time per-idle-period cost (e.g. OS page "
        "cache) rather than anything proportional to gap length. If it "
        "instead tracks free_ram_before dropping low, that supports the "
        "memory-pressure/page-eviction hypothesis more directly. Bring "
        "this table back for the next step -- no code change should be "
        "made from this data alone."
    )


if __name__ == "__main__":
    main()