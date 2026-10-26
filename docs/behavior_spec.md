# Behavior spec (v0 — edit before you record anything)

Rule: if a behavior is not written here with an observable criterion and a duration, the system must not alert on it.
The system flags events for a **human reviewer**. It never decides that someone cheated.

Camera assumption: fixed camera, whole row(s) visible, students seated, faces mostly visible. Write the real setup here: ____________

| Behavior | Observable criterion | Min duration | Detector | Innocent look-alikes that must NOT fire |
|---|---|---|---|---|
| `PHONE_USE` | A phone is detected within 0.8 shoulder-widths of the student's wrist (or inside their box if no wrist is visible) | 1.5 s | YOLO `cell phone` + pose wrist | Phone lying on a desk and not touched; phone held by the invigilator walking past; calculator/remote misdetected as phone |
| `GAZE_NEIGHBOR` | Head turned toward a seated neighbor in the same row (nose offset / shoulder width ≥ 0.20) | 3.0 s | Pose keypoints + geometry | Looking up while thinking; stretching; glancing at the clock or the door; looking at the invigilator; looking at the paper edge |
| `HAND_TO_NEIGHBOR` | A student's wrist is inside another student's body region | 1.0 s | Pose wrist + tracked boxes | Overlapping boxes in a crowded row; raising a hand; reaching for a dropped pen near a neighbor's seat |

## Known blind spots (say them out loud in the report)

- Looking at the person in front or behind: not detected (neighbor logic is same-row).
- Notes on the lap, smartwatch, earpiece: not detected.
- A 2D yaw proxy is not gaze. It says the head is turned, not what the eyes see.

## Calibration log

| date | behavior | parameter | old → new | evidence (val sessions only) |
|---|---|---|---|---|
|  |  |  |  |  |
