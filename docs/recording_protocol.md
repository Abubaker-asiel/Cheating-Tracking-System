# Recording protocol for your own mock exams

Goal: raw, untrimmed, labeled footage where the base rate of "nothing happening" is realistic.

## Before
- Written consent from every participant (what is recorded, who sees it, how long it is kept, right to withdraw). Do not use footage of people who did not agree.
- Fixed camera, fixed zoom, no auto-framing. Same angle as the real deployment. Note height and distance.
- Clock visible or a clap at the start so video time and the script time line up.

## Per session (at least 4, 10+ minutes each)
1. Record continuously. Do not trim, do not cut the quiet parts.
2. Run a **timestamped script** (`data/templates/session_script.csv`): who does which act, when. Include acts from the spec **and** the innocent look-alikes (thinking upward, stretching, glancing at the clock, hand raise).
3. Leave long unscripted stretches. Natural behavior is where your hard negatives come from.
4. Vary things between sessions: seating, lighting, glasses/hats, one session from a different angle or room if you can.

## After
- Label events (start/end, behavior) in CVAT or Label Studio, export to `ground_truth.csv` (template in `data/templates/`).
- Ask someone who did not build the system to label the held-out session **without seeing your system's output** (`--gt2` gives you Cohen's kappa between raters).
- Fill `data/splits.csv` (`session,split` with train/val/test), then `python -m invigil check-splits --freeze`. The `run` command refuses `test` sessions unless you pass `--final`.
- Keep the raw video. Never edit it.
