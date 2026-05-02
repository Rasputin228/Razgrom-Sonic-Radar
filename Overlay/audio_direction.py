import math

NUM_SECTORS = 16
SECTOR_WIDTH = 360 / NUM_SECTORS


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def normalize_angle(angle_degrees):
    return angle_degrees % 360


def angle_to_sector(angle_degrees):
    normalized = normalize_angle(angle_degrees)
    return int((normalized + SECTOR_WIDTH / 2) // SECTOR_WIDTH) % NUM_SECTORS


def direction_angle_from_balance(balance, is_back=False, swap_channels=False):
    normalized_balance = clamp(balance, -1.0, 1.0)
    if swap_channels:
        normalized_balance *= -1

    pan_angle = normalized_balance * 90
    if is_back:
        return normalize_angle(180 - pan_angle)
    return normalize_angle(pan_angle)


def angular_difference(target_degrees, source_degrees):
    return ((target_degrees - source_degrees + 180) % 360) - 180


def smooth_angle(previous_degrees, target_degrees, strength):
    if previous_degrees is None:
        return normalize_angle(target_degrees)

    normalized_strength = clamp(strength, 0.0, 1.0)
    delta = angular_difference(target_degrees, previous_degrees)
    return normalize_angle(previous_degrees + delta * normalized_strength)


def build_sector_levels(angle_degrees, level, spread=2):
    center = angle_to_sector(angle_degrees)
    peak = clamp(level, 0.0, 1.0)
    sectors = [0.0] * NUM_SECTORS
    sectors[center] = peak

    for distance in range(1, spread + 1):
        falloff = peak * math.pow(0.5, distance)
        sectors[(center - distance) % NUM_SECTORS] = max(sectors[(center - distance) % NUM_SECTORS], falloff)
        sectors[(center + distance) % NUM_SECTORS] = max(sectors[(center + distance) % NUM_SECTORS], falloff)

    return sectors

