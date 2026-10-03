"""Deterministic scene/face training coverage across every captured view."""


def training_view_and_mode(step: int, view_count: int) -> tuple[int, str]:
    if step < 0 or view_count < 1:
        raise ValueError("invalid training schedule")
    epoch, index = divmod(step, view_count)
    # Rotate occasional full-frame updates too: if the view count is a
    # multiple of 50, step % 50 would permanently make the same views full.
    if (index + epoch * 7) % 50 == 0:
        return index, "full"
    # Shift the mode assignment every epoch. A fixed step modulo silently
    # starved half the views whenever view_count mod 4 was 2.
    if epoch < 4:
        scene = (index + epoch) % 2 == 0
    else:
        scene = (index + epoch) % 4 == 0
    return index, "scene" if scene else "face"
