import json
import os

SAMPLE_RATE = 48000
BLOCK_SIZE = 512
FREQ_LOW = 40
FREQ_HIGH = 5000
SENSITIVITY = 350.0
COMPRESSION = 0.4
REAR_THRESHOLD = 1200
NOISE_FLOOR = 0.018
CONFIG_FILE = "config.json"
DIAGNOSTIC_REPORT_FILE = "diagnostic_report.json"

TRANS_COLOR = "#000001"

COLOR_PROFILES = {
    "orange": {
        "name": "Оранжевый",
        "grid": "#444444",
        "active": "#ff9900",
        "danger": "#ff3300",
        "muted": "#443300",
        "text": "#ffcc66",
    },
    "blue": {
        "name": "Сине-белый",
        "grid": "#5f7288",
        "active": "#4fd8ff",
        "danger": "#ffffff",
        "muted": "#1d3f4a",
        "text": "#d9f6ff",
    },
    "contrast": {
        "name": "Высокий контраст",
        "grid": "#777777",
        "active": "#ffff00",
        "danger": "#ff0000",
        "muted": "#555500",
        "text": "#ffffff",
    },
}

PROFILE_PRESETS = {
    "Custom": {},
    "CS2 / footsteps": {
        "sensitivity": 420.0,
        "noise_floor": 0.026,
        "sector_spread": 2,
        "visual_mode": "minimal",
        "color_profile": "contrast",
        "opacity": 0.82,
    },
    "Tarkov / tactical": {
        "sensitivity": 520.0,
        "noise_floor": 0.032,
        "sector_spread": 3,
        "visual_mode": "radar",
        "color_profile": "orange",
        "opacity": 0.78,
    },
    "Arena Breakout": {
        "sensitivity": 470.0,
        "noise_floor": 0.028,
        "sector_spread": 2,
        "visual_mode": "minimal",
        "color_profile": "blue",
        "opacity": 0.84,
    },
    "Desktop test": {
        "sensitivity": 260.0,
        "noise_floor": 0.018,
        "sector_spread": 1,
        "visual_mode": "radar",
        "color_profile": "orange",
        "opacity": 0.9,
    },
}

DEFAULT_SETTINGS = {
    "profile_name": "Custom",
    "sensitivity": SENSITIVITY,
    "size": 320,
    "opacity": 0.85,
    "color_profile": "orange",
    "show_labels": True,
    "swap_channels": False,
    "sector_spread": 2,
    "noise_floor": NOISE_FLOOR,
    "visual_mode": "radar",
    "edge_indicators": True,
    "direction_smoothing": 0.35,
    "overlay_x": 100,
    "overlay_y": 100,
}


def log_message(msg):
    try:
        with open("overlay_debug.txt", "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except:
        pass


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_message(f"Config read error: {e}")
        return {}


def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_message(f"Config write error: {e}")


def apply_saved_settings(settings, saved_config):
    settings["profile_name"] = saved_config.get("profile_name", settings["profile_name"])
    settings["sensitivity"] = float(saved_config.get("sensitivity", settings["sensitivity"]))
    settings["size"] = int(saved_config.get("size", settings["size"]))
    settings["opacity"] = float(saved_config.get("opacity", settings["opacity"]))
    settings["color_profile"] = saved_config.get("color_profile", settings["color_profile"])
    settings["show_labels"] = bool(saved_config.get("show_labels", settings["show_labels"]))
    settings["swap_channels"] = bool(saved_config.get("swap_channels", settings["swap_channels"]))
    settings["sector_spread"] = int(saved_config.get("sector_spread", settings["sector_spread"]))
    settings["noise_floor"] = float(saved_config.get("noise_floor", settings["noise_floor"]))
    settings["visual_mode"] = saved_config.get("visual_mode", settings["visual_mode"])
    settings["edge_indicators"] = bool(saved_config.get("edge_indicators", settings["edge_indicators"]))
    settings["direction_smoothing"] = float(saved_config.get("direction_smoothing", settings["direction_smoothing"]))
    settings["overlay_x"] = int(saved_config.get("overlay_x", settings["overlay_x"]))
    settings["overlay_y"] = int(saved_config.get("overlay_y", settings["overlay_y"]))

    settings["sensitivity"] = clamp(settings["sensitivity"], 80.0, 900.0)
    settings["size"] = int(clamp(settings["size"], 180, 800))
    settings["opacity"] = clamp(settings["opacity"], 0.35, 1.0)
    settings["sector_spread"] = int(clamp(settings["sector_spread"], 1, 3))
    settings["noise_floor"] = clamp(settings["noise_floor"], 0.002, 0.25)
    settings["direction_smoothing"] = clamp(settings["direction_smoothing"], 0.05, 1.0)
    settings["overlay_x"] = int(clamp(settings["overlay_x"], -4000, 4000))
    settings["overlay_y"] = int(clamp(settings["overlay_y"], -4000, 4000))

    if settings["visual_mode"] not in ("radar", "minimal"):
        settings["visual_mode"] = "radar"
    if settings["color_profile"] not in COLOR_PROFILES:
        settings["color_profile"] = "orange"
    if settings["profile_name"] not in PROFILE_PRESETS:
        settings["profile_name"] = "Custom"


def build_saved_config(settings, window, audio_source, fallback_audio=None):
    return {
        "profile_name": settings["profile_name"],
        "window": window,
        "audio": audio_source.get("name") if audio_source else fallback_audio,
        "audio_kind": audio_source.get("kind") if audio_source else "loopback",
        "sensitivity": settings["sensitivity"],
        "size": settings["size"],
        "opacity": settings["opacity"],
        "color_profile": settings["color_profile"],
        "show_labels": settings["show_labels"],
        "swap_channels": settings["swap_channels"],
        "sector_spread": settings["sector_spread"],
        "noise_floor": settings["noise_floor"],
        "visual_mode": settings["visual_mode"],
        "edge_indicators": settings["edge_indicators"],
        "direction_smoothing": settings["direction_smoothing"],
        "overlay_x": settings["overlay_x"],
        "overlay_y": settings["overlay_y"],
    }
