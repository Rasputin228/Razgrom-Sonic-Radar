def classify_audio_event(level, previous_level, centroid_hz, noise_floor, is_moving=False):
    if level <= noise_floor:
        return "IDLE"

    attack = level - previous_level

    if level >= 0.75 and attack >= 0.12:
        return "IMPACT"

    if not is_moving and 0.12 <= level <= 0.72 and attack >= 0.035 and 180 <= centroid_hz <= 2200:
        return "STEP"

    if centroid_hz > 2800 and level >= 0.22:
        return "SHARP"

    if centroid_hz < 420 and level >= noise_floor * 2.0:
        return "LOW"

    return "SOUND"

