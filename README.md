# Invigil

Exam-review tool that flags suspected cheating **for a human reviewer**.
Upload a video → students are detected and tracked → green/red boxes → one screenshot per incident → database record → alert in the desktop app, a browser dashboard, and (optionally) Firebase.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate     # use Python 3.12 or 3.13 if torch fails on newer versions
pip install -r requirements.txt
```

## Try the interface without a video

```bash
python -m invigil demo                         # fake incidents + drawn evidence frames -> demo.db
python -m invigil app --db demo.db             # desktop app
python -m invigil dashboard --db demo.db       # browser dashboard on http://127.0.0.1:8765
```

## Real use

```bash
python -m invigil app                                    # desktop app: Monitor, Incidents, Settings
python -m invigil dashboard                              # web dashboard on the same database
python -m invigil run exam01.mp4 --session s01           # headless; uploads to Firebase if firebase.json exists
python -m invigil run exam01.mp4 --session s01 --mode baseline_phone    # the "phone visible = alert" baseline
python -m invigil check-splits --freeze                  # lock the held-out test sessions
python -m invigil evaluate --gt data/ground_truth.csv    # precision/recall, false alerts/hour, CIs, kappa
pytest
```

**Desktop app.** *Monitor*: upload a video, watch tracking live, alerts appear as cards you can confirm or dismiss. *Incidents*: filterable table with evidence thumbnails; double-click for the full frame (peak and onset). *Settings*: Firebase and dashboard. The app icon is set at runtime (window and Dock/taskbar).

**Web dashboard.** KPI cards, review-status donut, flags by behavior, flags over exam time, incident table, evidence drawer (keys: C confirm, D dismiss, Esc close), CSV export. It reads the same SQLite file, refreshes every 5 s, and is bound to `127.0.0.1` only: exam evidence should not be reachable from the network.

## Firebase (saving screenshots)

1. Firebase console → create a project → **Firestore Database** (and **Storage**, if your plan includes it).
2. Project settings → **Service accounts** → *Generate new private key*. Save it next to the app as `serviceAccountKey.json`. **Never commit it** (`.gitignore` already excludes it; your GitHub repo is public).
3. Copy `firebase.example.json` to `firebase.json` and fill in the bucket name, or fill the same fields in the app under *Settings → Save and connect*.
4. Choose how photos are stored:
   - `"mode": "storage"`: images go to Cloud Storage, metadata to Firestore.
   - `"mode": "firestore_inline"`: no Storage bucket needed; a downsized JPEG (max 720 px) is embedded in each Firestore document. Use this if Storage is unavailable on your plan.
5. Keep the bucket and Firestore rules **locked** (the default). The app uses the Admin SDK, which does not need public access. These are photos of students.

Uploads run in a background thread and never slow the video. Failures are stored on the incident and retried (*Settings → Upload pending now*, or at next start). Review decisions are synced too.

## How it decides

1. YOLOv8-pose gives people + 17 keypoints; ByteTrack gives each student a stable ID; a second YOLOv8 pass finds phones.
2. `rules.py` checks the three behaviors in `docs/behavior_spec.md` (phone near wrist, head turned toward a neighbor, wrist inside a neighbor's body region).
3. Flags become **events**: a behavior must persist 1–3 s to open, short dropouts don't split it, start is back-dated to the first flagged frame. One onset screenshot (saved at once, alert fires) and one best-frame screenshot (saved at close).
4. Every threshold lives in `config.yaml` and is stored with each run.

## Workflow for a result you can defend

1. Edit `docs/behavior_spec.md` until you agree with every row.
2. Record 4+ mock sessions (`docs/recording_protocol.md`), label them into `ground_truth.csv`.
3. Fill `data/splits.csv`, run `check-splits --freeze`. `run` refuses `test` sessions without `--final`.
4. Run `rules` and `baseline`, calibrate on **val only**.
5. Have someone who didn't build it label the test session blind, run with `--final`, then `evaluate`.

## Honest status

- **Tested:** rules, geometry, database + migration, split guard, evaluation math, cloud queue (fake backend), dashboard API and page (headless Chromium and jsdom), Qt screens rendered offscreen, real YOLO + tracking through the Qt worker thread on a test video. 52 tests.
- **Not tested:** a live Firebase project (the backend is only exercised up to the first network call), how the screens look with macOS system fonts, and anything on real exam footage.
- **Thresholds are uncalibrated guesses**, especially `yaw_threshold`. Pretrained COCO detectors are weak on phones at classroom distance; fine-tune on your own frames if recall is poor.
- "Signal strength" is a heuristic score, not a probability.
- A 2D yaw proxy is not gaze, and neighbor logic only covers the same row.
- Making a standalone `.app`/`.exe` (PyInstaller) is not set up. `invigil/assets/icon.icns` and `icon.ico` are ready for it; torch and Ultralytics make bundling heavy.
