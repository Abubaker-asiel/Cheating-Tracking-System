"""Human labels and colours for behaviors, shared by the desktop app and the dashboard."""

BEHAVIOR_LABELS = {
    "PHONE_USE": "Phone use",
    "GAZE_NEIGHBOR": "Peeking at neighbor",
    "HAND_TO_NEIGHBOR": "Reaching to neighbor",
}
# (strong, soft background)
BEHAVIOR_COLORS = {
    "PHONE_USE": ("#D8432B", "#F8E4DE"),
    "GAZE_NEIGHBOR": ("#B9770E", "#F6EBD3"),
    "HAND_TO_NEIGHBOR": ("#6B4BA3", "#EAE3F4"),
}
STATUS_LABELS = {"pending": "Needs review", "confirmed": "Confirmed", "dismissed": "False alarm"}


def label(behavior: str) -> str:
    return BEHAVIOR_LABELS.get(behavior, behavior.replace("_", " ").title())


def colors(behavior: str) -> tuple:
    return BEHAVIOR_COLORS.get(behavior, ("#555555", "#E8E8E8"))
