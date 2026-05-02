import sys
import time
import threading
import math
import traceback
import ctypes
from ctypes import wintypes
import os
import json

from audio_direction import build_sector_levels, direction_angle_from_balance
from audio_events import classify_audio_event

# --- ЛОГГЕР ---
def log_message(msg):
    try:
        with open("overlay_debug.txt", "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except: pass

def handle_exception(exc_type, exc_value, exc_traceback):
    sys.exit(1)

sys.excepthook = handle_exception

try:
    import tkinter as tk
    from tkinter import ttk
    import numpy as np
    import soundcard as sc
    from scipy import signal
except Exception as e:
    log_message(f"Import Error: {e}")
    sys.exit(1)

# --- НАСТРОЙКИ ---
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

# ЦВЕТА
TRANS_COLOR = "#000001"
COLOR_GRID = "#444444"
COLOR_ACTIVE = "#ff9900"
COLOR_DANGER = "#ff3300"

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

settings = {
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
    "overlay_x": 100,
    "overlay_y": 100,
}

# Глобальные переменные
sector_data = [0.0] * 16
is_moving = False
is_human = False
running = True
target_window_title = ""
selected_speaker_id = None 
selected_audio_source = None
current_peak = 0.0
current_confidence = 0.0
current_event = "IDLE"
previous_level = 0.0
audio_status = "IDLE"
audio_error_message = ""

# --- CTYPES ---
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
MOVE_KEYS = (0x57, 0x41, 0x53, 0x44)


def is_key_down(vk_code):
    return bool(user32.GetAsyncKeyState(vk_code) & 0x8000)

def get_open_windows():
    titles = []
    def enum_windows_proc(hwnd, lParam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            buff = ctypes.create_unicode_buffer(255)
            user32.GetWindowTextW(hwnd, buff, 255)
            t = buff.value
            if t not in ["Program Manager", "Settings", "Razgrom Injector", "Razgrom Config"]:
                titles.append(t)
        return True
    user32.EnumWindows(WNDENUMPROC(enum_windows_proc), 0)
    return sorted(list(set(titles)))


def get_audio_sources():
    sources = []
    try:
        for speaker in sc.all_speakers():
            sources.append({
                "label": f"OUTPUT LOOPBACK | {speaker.name}",
                "name": speaker.name,
                "kind": "loopback",
            })
    except Exception as e:
        log_message(f"Speaker scan error: {e}")

    try:
        for mic in sc.all_microphones(include_loopback=False):
            sources.append({
                "label": f"MIC INPUT       | {mic.name}",
                "name": mic.name,
                "kind": "microphone",
            })
    except Exception as e:
        log_message(f"Microphone scan error: {e}")

    return sources


def open_audio_recorder_source(source):
    if source and source.get("kind") == "microphone":
        return sc.get_microphone(id=str(source["name"]), include_loopback=False)

    if source and source.get("kind") == "loopback":
        return sc.get_microphone(id=str(source["name"]), include_loopback=True)

    return sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)

# --- ЛАУНЧЕР ---
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log_message(f"Config read error: {e}")
        return {}

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_message(f"Config write error: {e}")

def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))

def apply_saved_settings(saved_config):
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
    settings["overlay_x"] = int(saved_config.get("overlay_x", settings["overlay_x"]))
    settings["overlay_y"] = int(saved_config.get("overlay_y", settings["overlay_y"]))
    settings["sensitivity"] = clamp(settings["sensitivity"], 80.0, 900.0)
    settings["size"] = int(clamp(settings["size"], 180, 800))
    settings["opacity"] = clamp(settings["opacity"], 0.35, 1.0)
    settings["sector_spread"] = int(clamp(settings["sector_spread"], 1, 3))
    settings["noise_floor"] = clamp(settings["noise_floor"], 0.002, 0.25)
    settings["overlay_x"] = int(clamp(settings["overlay_x"], -4000, 4000))
    settings["overlay_y"] = int(clamp(settings["overlay_y"], -4000, 4000))
    if settings["visual_mode"] not in ("radar", "minimal"):
        settings["visual_mode"] = "radar"
    if settings["color_profile"] not in COLOR_PROFILES:
        settings["color_profile"] = "orange"
    if settings["profile_name"] not in PROFILE_PRESETS:
        settings["profile_name"] = "Custom"

def build_saved_config(window, audio_source):
    return {
        "profile_name": settings["profile_name"],
        "window": window,
        "audio": audio_source.get("name") if audio_source else selected_speaker_id,
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
        "overlay_x": settings["overlay_x"],
        "overlay_y": settings["overlay_y"],
    }

def measure_noise_floor(source, sensitivity, seconds=3.0):
    levels = []
    frames = max(1, int(seconds * SAMPLE_RATE / BLOCK_SIZE))
    with open_audio_recorder_source(source).recorder(samplerate=SAMPLE_RATE, channels=2, blocksize=BLOCK_SIZE) as recorder:
        for _ in range(frames):
            data = recorder.record(numframes=BLOCK_SIZE)
            channel_sum = math.sqrt(float(np.mean(data[:, 0] ** 2))) + math.sqrt(float(np.mean(data[:, 1] ** 2)))
            levels.append(float(np.power(channel_sum * sensitivity, COMPRESSION)))

    if not levels:
        return NOISE_FLOOR

    percentile = float(np.percentile(levels, 90))
    return clamp(percentile * 1.7, 0.006, 0.25)

def diagnose_audio_source(source, sensitivity, seconds=1.0):
    levels = []
    balances = []
    centroids = []
    frames = max(1, int(seconds * SAMPLE_RATE / BLOCK_SIZE))
    with open_audio_recorder_source(source).recorder(samplerate=SAMPLE_RATE, channels=2, blocksize=BLOCK_SIZE) as recorder:
        for _ in range(frames):
            data = recorder.record(numframes=BLOCK_SIZE)
            rms_l = math.sqrt(float(np.mean(data[:, 0] ** 2)))
            rms_r = math.sqrt(float(np.mean(data[:, 1] ** 2)))
            channel_sum = rms_l + rms_r
            level = float(np.power(channel_sum * sensitivity, COMPRESSION))
            balance = (rms_r - rms_l) / (channel_sum + 0.000001)
            levels.append(level)
            balances.append(balance)

            freqs = np.fft.rfft(data[:, 0] + data[:, 1])
            mags = np.abs(freqs)
            mag_sum = np.sum(mags)
            if mag_sum > 0:
                centroids.append(float((np.sum(np.arange(len(mags)) * mags) / mag_sum) * (SAMPLE_RATE / BLOCK_SIZE)))

    if not levels:
        return {
            "level": 0.0,
            "peak": 0.0,
            "balance": 0.0,
            "centroid": 0.0,
            "frames": 0,
        }

    return {
        "level": float(np.mean(levels)),
        "peak": float(np.max(levels)),
        "balance": float(np.mean(balances)),
        "centroid": float(np.mean(centroids)) if centroids else 0.0,
        "frames": len(levels),
    }

def write_diagnostic_report(window, audio_source, last_report=None):
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "selected_window": window,
        "selected_audio_source": audio_source,
        "settings": settings.copy(),
        "audio_status": audio_status,
        "audio_error": audio_error_message,
        "last_measurement": last_report,
        "available_audio_sources": get_audio_sources(),
    }
    with open(DIAGNOSTIC_REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return os.path.abspath(DIAGNOSTIC_REPORT_FILE)

def show_launcher():
    global target_window_title, selected_speaker_id, selected_audio_source
    
    saved_config = load_config()
    apply_saved_settings(saved_config)

    root = tk.Tk()
    root.title("Razgrom Config")
    root.geometry("520x760")
    root.minsize(500, 560)
    root.resizable(True, True)
    root.configure(bg="#111")

    footer = tk.Frame(root, bg="#111")
    footer.pack(side="bottom", fill="x", padx=15, pady=(8, 12))
    
    style = ttk.Style()
    style.theme_use('clam')
    
    tk.Label(root, text="RAZGROM RADAR v5.1 ACCESS", bg="#111", fg="orange", font=("Impact", 18)).pack(pady=5)

    tk.Label(root, text="1. Следить за окном:", bg="#111", fg="#aaa").pack(anchor="w", padx=15)
    list_win = tk.Listbox(root, bg="#222", fg="white", height=6, selectbackground="orange", exportselection=False)
    list_win.pack(fill="x", padx=15)
    
    windows = get_open_windows()
    for i, w in enumerate(windows): 
        list_win.insert(tk.END, w)
        # Автовыбор сохраненного окна
        if saved_config.get("window") == w:
            list_win.selection_set(i)
            list_win.activate(i)

    tk.Label(root, text="2. Источник звука:", bg="#111", fg="#aaa").pack(anchor="w", padx=15, pady=(10,0))
    list_aud = tk.Listbox(root, bg="#222", fg="white", height=4, selectbackground="orange", exportselection=False)
    list_aud.pack(fill="x", padx=15)
    
    audio_sources = get_audio_sources()
    saved_audio_name = saved_config.get("audio")
    saved_audio_kind = saved_config.get("audio_kind", "loopback")
    for i, source in enumerate(audio_sources):
        list_aud.insert(tk.END, source["label"])
        if saved_audio_name == source["name"] and saved_audio_kind == source["kind"]:
            list_aud.selection_set(i)
            list_aud.activate(i)
    if not audio_sources:
        list_aud.insert(tk.END, "Default output loopback")
    elif not list_aud.curselection():
        list_aud.selection_set(0)
        list_aud.activate(0)

    tk.Label(
        root,
        text="Для игры выбирайте OUTPUT LOOPBACK. Чтобы Discord, музыка или микрофон не мешали, выводите игру на отдельное устройство или VB-CABLE и выбирайте его здесь.",
        bg="#111", fg="#777", wraplength=450, justify="left"
    ).pack(anchor="w", padx=15, pady=(4, 0))

    settings_frame = tk.LabelFrame(root, text="3. Доступность и видимость", bg="#111", fg="#aaa", padx=10, pady=8)
    settings_frame.pack(fill="x", padx=15, pady=(10, 0))

    sensitivity_var = tk.DoubleVar(value=settings["sensitivity"])
    size_var = tk.IntVar(value=settings["size"])
    opacity_var = tk.DoubleVar(value=settings["opacity"])
    labels_var = tk.BooleanVar(value=settings["show_labels"])
    swap_channels_var = tk.BooleanVar(value=settings["swap_channels"])
    sector_spread_var = tk.IntVar(value=settings["sector_spread"])
    noise_floor_var = tk.DoubleVar(value=settings["noise_floor"])
    visual_mode_var = tk.StringVar(value=settings["visual_mode"])
    color_profile_var = tk.StringVar(value=settings["color_profile"])
    preset_var = tk.StringVar(value=settings["profile_name"])

    preset_row = tk.Frame(settings_frame, bg="#111")
    preset_row.pack(fill="x", pady=(0, 6))
    tk.Label(preset_row, text="Профиль", bg="#111", fg="#ddd", width=15, anchor="w").pack(side="left")
    preset_combo = ttk.Combobox(preset_row, textvariable=preset_var, state="readonly", width=22)
    preset_combo["values"] = list(PROFILE_PRESETS.keys())
    preset_combo.pack(side="left")

    def apply_preset(_event=None):
        preset = PROFILE_PRESETS.get(preset_var.get(), {})
        if not preset:
            return
        sensitivity_var.set(preset.get("sensitivity", sensitivity_var.get()))
        noise_floor_var.set(preset.get("noise_floor", noise_floor_var.get()))
        sector_spread_var.set(preset.get("sector_spread", sector_spread_var.get()))
        visual_mode_var.set(preset.get("visual_mode", visual_mode_var.get()))
        color_profile_var.set(preset.get("color_profile", color_profile_var.get()))
        opacity_var.set(preset.get("opacity", opacity_var.get()))
        update_profile_hint()

    preset_combo.bind("<<ComboboxSelected>>", apply_preset)

    def add_scale(label, variable, from_, to_, resolution=1):
        row = tk.Frame(settings_frame, bg="#111")
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, bg="#111", fg="#ddd", width=15, anchor="w").pack(side="left")
        scale = tk.Scale(
            row, from_=from_, to=to_, resolution=resolution, orient="horizontal",
            variable=variable, bg="#111", fg="#ddd", troughcolor="#222",
            highlightthickness=0, length=270
        )
        scale.pack(side="left", fill="x", expand=True)

    add_scale("Чувствительность", sensitivity_var, 100, 850, 10)
    add_scale("Размер радара", size_var, 180, 700, 10)
    add_scale("Непрозрачность", opacity_var, 0.35, 1.0, 0.05)
    add_scale("Ширина сектора", sector_spread_var, 1, 3, 1)
    add_scale("Порог шума", noise_floor_var, 0.002, 0.25, 0.002)

    profile_row = tk.Frame(settings_frame, bg="#111")
    profile_row.pack(fill="x", pady=6)
    tk.Label(profile_row, text="Цвета", bg="#111", fg="#ddd", width=15, anchor="w").pack(side="left")
    profile_combo = ttk.Combobox(profile_row, textvariable=color_profile_var, state="readonly", width=22)
    profile_combo["values"] = list(COLOR_PROFILES.keys())
    profile_combo.pack(side="left")
    profile_hint = tk.Label(profile_row, text=COLOR_PROFILES[color_profile_var.get()]["name"], bg="#111", fg="#aaa")
    profile_hint.pack(side="left", padx=8)

    def update_profile_hint(_event=None):
        profile_hint.config(text=COLOR_PROFILES.get(color_profile_var.get(), COLOR_PROFILES["orange"])["name"])

    profile_combo.bind("<<ComboboxSelected>>", update_profile_hint)

    mode_row = tk.Frame(settings_frame, bg="#111")
    mode_row.pack(fill="x", pady=6)
    tk.Label(mode_row, text="Режим HUD", bg="#111", fg="#ddd", width=15, anchor="w").pack(side="left")
    mode_combo = ttk.Combobox(mode_row, textvariable=visual_mode_var, state="readonly", width=22)
    mode_combo["values"] = ("radar", "minimal")
    mode_combo.pack(side="left")

    calibration_row = tk.Frame(settings_frame, bg="#111")
    calibration_row.pack(fill="x", pady=(6, 2))
    calibration_status = tk.Label(calibration_row, text="Калибровка тишины: готово", bg="#111", fg="#aaa", anchor="w")
    calibration_status.pack(side="left", fill="x", expand=True)
    last_diagnostic_report = {"data": None}

    def selected_source_from_list():
        try:
            return audio_sources[list_aud.curselection()[0]]
        except:
            return None

    def run_noise_calibration():
        source = selected_source_from_list()
        calibration_status.config(text="Калибровка тишины: слушаю 3 секунды...", fg="#ffcc66")
        calibrate_button.config(state="disabled")

        def worker():
            try:
                measured = measure_noise_floor(source, float(sensitivity_var.get()), seconds=3.0)
                root.after(0, lambda: finish_calibration(measured, None))
            except Exception as e:
                error_text = str(e)
                root.after(0, lambda: finish_calibration(None, error_text))

        threading.Thread(target=worker, daemon=True).start()

    def finish_calibration(value, error):
        calibrate_button.config(state="normal")
        if error:
            calibration_status.config(text=f"Калибровка не удалась: {error}", fg="#ff6666")
            return
        noise_floor_var.set(round(value, 3))
        calibration_status.config(text=f"Порог шума установлен: {value:.3f}", fg="#66ff99")

    def run_audio_diagnostics():
        source = selected_source_from_list()
        calibration_status.config(text="Диагностика: измеряю источник 1 секунду...", fg="#ffcc66")
        diagnostics_button.config(state="disabled")

        def worker():
            try:
                report = diagnose_audio_source(source, float(sensitivity_var.get()), seconds=1.0)
                root.after(0, lambda: finish_diagnostics(report, None))
            except Exception as e:
                error_text = str(e)
                root.after(0, lambda: finish_diagnostics(None, error_text))

        threading.Thread(target=worker, daemon=True).start()

    def finish_diagnostics(report, error):
        diagnostics_button.config(state="normal")
        if error:
            calibration_status.config(text=f"Диагностика не удалась: {error}", fg="#ff6666")
            return
        side = "CENTER"
        if report["balance"] > 0.12:
            side = "RIGHT"
        elif report["balance"] < -0.12:
            side = "LEFT"
        calibration_status.config(
            text=f"AVG {report['level']:.3f} | PEAK {report['peak']:.3f} | {side} | {report['centroid']:.0f} Hz",
            fg="#66ff99"
        )
        last_diagnostic_report["data"] = report

    calibrate_button = tk.Button(
        settings_frame,
        text="КАЛИБРОВАТЬ ТИШИНУ 3 СЕК",
        bg="#333",
        fg="#fff",
        activebackground="#444",
        activeforeground="#fff",
        command=run_noise_calibration
    )
    calibrate_button.pack(fill="x", pady=(4, 6))

    diagnostics_button = tk.Button(
        settings_frame,
        text="ДИАГНОСТИКА ИСТОЧНИКА 1 СЕК",
        bg="#222",
        fg="#fff",
        activebackground="#444",
        activeforeground="#fff",
        command=run_audio_diagnostics
    )
    diagnostics_button.pack(fill="x", pady=(0, 6))

    def export_diagnostic_report():
        try:
            window = list_win.get(list_win.curselection())
        except:
            window = ""
        source = selected_source_from_list()
        try:
            path = write_diagnostic_report(window, source, last_diagnostic_report["data"])
            calibration_status.config(text=f"Отчет сохранен: {path}", fg="#66ff99")
        except Exception as e:
            calibration_status.config(text=f"Отчет не сохранен: {e}", fg="#ff6666")

    report_button = tk.Button(
        settings_frame,
        text="СОХРАНИТЬ ДИАГНОСТИЧЕСКИЙ ОТЧЕТ",
        bg="#222",
        fg="#fff",
        activebackground="#444",
        activeforeground="#fff",
        command=export_diagnostic_report
    )
    report_button.pack(fill="x", pady=(0, 6))

    tk.Checkbutton(
        settings_frame, text="Показывать подписи направлений", variable=labels_var,
        bg="#111", fg="#ddd", activebackground="#111", activeforeground="#fff",
        selectcolor="#222"
    ).pack(anchor="w", pady=4)
    tk.Checkbutton(
        settings_frame, text="Поменять левый/правый канал местами", variable=swap_channels_var,
        bg="#111", fg="#ddd", activebackground="#111", activeforeground="#fff",
        selectcolor="#222"
    ).pack(anchor="w", pady=4)

    def on_start():
        global target_window_title, selected_speaker_id, selected_audio_source
        
        # Получаем данные
        try: target_window_title = list_win.get(list_win.curselection())
        except: target_window_title = ""
        
        try:
            selected_audio_source = audio_sources[list_aud.curselection()[0]]
            selected_speaker_id = selected_audio_source["name"]
        except:
            selected_audio_source = None
            selected_speaker_id = None

        settings["sensitivity"] = float(sensitivity_var.get())
        settings["size"] = int(size_var.get())
        settings["opacity"] = float(opacity_var.get())
        settings["profile_name"] = preset_var.get()
        settings["color_profile"] = color_profile_var.get()
        settings["show_labels"] = bool(labels_var.get())
        settings["swap_channels"] = bool(swap_channels_var.get())
        settings["sector_spread"] = int(sector_spread_var.get())
        settings["noise_floor"] = float(noise_floor_var.get())
        settings["visual_mode"] = visual_mode_var.get()
        
        save_config(build_saved_config(target_window_title, selected_audio_source))
        
        root.destroy()

    def on_close(): sys.exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    tk.Label(
        footer,
        text="Правый клик по радару открывает меню. Оверлей работает только с аудиопотоком Windows.",
        bg="#111", fg="#777", wraplength=430, justify="center"
    ).pack(pady=(0, 8), fill="x")
    tk.Button(
        footer,
        text="ЗАПУСТИТЬ РАДАР",
        bg="orange",
        fg="black",
        activebackground="#ffb347",
        activeforeground="black",
        font=("Arial", 13, "bold"),
        command=on_start
    ).pack(fill="x", ipady=6)
    root.bind("<Return>", lambda _event: on_start())
    root.mainloop()

# --- АУДИО ДВИЖОК ---
def audio_loop():
    global sector_data, is_moving, is_human, running, current_peak, current_confidence, current_event, previous_level, audio_status, audio_error_message
    
    try: np.fromstring(b'\x00'*4, dtype=np.float32)
    except:
        def fromstring_patch(string, dtype=float, count=-1, sep=''):
            if sep == '': return np.frombuffer(string, dtype=dtype, count=count)
            return np.fromiter(string.split(sep), dtype=dtype)
        np.fromstring = fromstring_patch

    try: b, a = signal.butter(4, [FREQ_LOW, FREQ_HIGH], btype='band', fs=SAMPLE_RATE)
    except: return

    while running:
        try:
            mic = open_audio_recorder_source(selected_audio_source)
            audio_status = "RUNNING"
            audio_error_message = ""

            with mic.recorder(samplerate=SAMPLE_RATE, channels=2, blocksize=BLOCK_SIZE) as recorder:
                while running:
                    data = recorder.record(numframes=BLOCK_SIZE)
            
                    if target_window_title:
                        try:
                            hwnd = user32.GetForegroundWindow()
                            buff = ctypes.create_unicode_buffer(255)
                            user32.GetWindowTextW(hwnd, buff, 255)
                            if target_window_title not in buff.value and "Razgrom" not in buff.value and buff.value != "":
                                sector_data = [0.0] * 16
                                current_peak = 0.0
                                current_confidence = 0.0
                                current_event = "IDLE"
                                previous_level = 0.0
                                time.sleep(0.2)
                                continue
                        except: pass

                    is_moving = False
                    try:
                        is_moving = any(is_key_down(key) for key in MOVE_KEYS)
                    except: pass

                    filtered = signal.lfilter(b, a, data, axis=0)
                    raw_l = filtered[:, 0]
                    raw_r = filtered[:, 1]
                    
                    rms_l = math.sqrt(float(np.mean(raw_l ** 2)))
                    rms_r = math.sqrt(float(np.mean(raw_r ** 2)))
                    channel_sum = rms_l + rms_r
                    balance = (rms_r - rms_l) / (channel_sum + 0.000001)

                    sensitivity = settings.get("sensitivity", SENSITIVITY)
                    total = np.power(channel_sum * sensitivity, COMPRESSION)
                    
                    if is_moving:
                        total *= 0.45

                    current_peak = min(total, 1.0)
                    current_confidence = clamp((abs(balance) * 0.45) + (current_peak * 0.55), 0.0, 1.0)
                    
                    is_back = False
                    centroid = 0.0
                    if total > 0.05:
                        freqs = np.fft.rfft(data[:, 0] + data[:, 1])
                        mags = np.abs(freqs)
                        if np.sum(mags) > 0:
                            centroid = (np.sum(np.arange(len(mags)) * mags) / np.sum(mags)) * (SAMPLE_RATE / BLOCK_SIZE)
                            if centroid < REAR_THRESHOLD: is_back = True

                    noise_floor = settings.get("noise_floor", NOISE_FLOOR)
                    current_event = classify_audio_event(total, previous_level, centroid, noise_floor, is_moving=is_moving)
                    previous_level = (previous_level * 0.72) + (total * 0.28)

                    if total > noise_floor:
                        angle = direction_angle_from_balance(
                            balance,
                            is_back=is_back,
                            swap_channels=settings.get("swap_channels", False)
                        )
                        val = min(total, 1.0)
                        target = build_sector_levels(angle, val, spread=settings.get("sector_spread", 2))

                        for i in range(16):
                            if target[i] > sector_data[i]: sector_data[i] = target[i]
                    
                    is_human = total > 0.6
        except Exception as e:
            audio_status = "ERROR"
            audio_error_message = str(e)
            current_event = "AUDIO ERROR"
            current_peak = 0.0
            current_confidence = 0.0
            sector_data = [0.0] * 16
            log_message(f"Audio loop error: {e}")
            time.sleep(2)

# --- GUI ---
class RadarOverlay:
    def __init__(self, root):
        self.root = root
        self.root.title("Razgrom Overlay")
        self.root.overrideredirect(True)
        self.width = settings["size"]
        self.height = settings["size"]
        self.root.geometry(f"{self.width}x{self.height}+{settings['overlay_x']}+{settings['overlay_y']}")
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", TRANS_COLOR)
        try:
            self.root.wm_attributes("-alpha", settings["opacity"])
        except:
            pass
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg=TRANS_COLOR, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind('<Button-1>', self.start_move)
        self.canvas.bind('<B1-Motion>', self.do_move)
        self.canvas.bind('<Button-3>', self.show_context_menu)
        
        self.start_x = 0
        self.start_y = 0
        self.blocks_gfx = [] 
        self.profile = COLOR_PROFILES.get(settings["color_profile"], COLOR_PROFILES["orange"])
        self.status_text = None
        self.event_text = None
        self.peak_bar = None
        self.confidence_text = None
        self.last_config_save = 0
        self.menu = tk.Menu(root, tearoff=0, bg="#151515", fg="#eeeeee", activebackground="#333333")
        self.menu.add_command(label="Скрыть / показать подписи", command=self.toggle_labels)
        self.menu.add_command(label="Переключить HUD", command=self.toggle_visual_mode)
        test_menu = tk.Menu(self.menu, tearoff=0, bg="#151515", fg="#eeeeee", activebackground="#333333")
        test_menu.add_command(label="Вперед", command=lambda: self.test_direction(0))
        test_menu.add_command(label="Вправо", command=lambda: self.test_direction(90))
        test_menu.add_command(label="Назад", command=lambda: self.test_direction(180))
        test_menu.add_command(label="Влево", command=lambda: self.test_direction(270))
        self.menu.add_cascade(label="Тест направлений", menu=test_menu)
        self.menu.add_command(label="Закрыть радар", command=self.close)
        self.init_graphics()
        self.update_gui()

    def start_move(self, event):
        self.start_x = event.x
        self.start_y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + (event.x - self.start_x)
        y = self.root.winfo_y() + (event.y - self.start_y)
        self.root.geometry(f"+{x}+{y}")
        settings["overlay_x"] = x
        settings["overlay_y"] = y
        self.save_layout_throttled()

    def start_resize(self, event):
        self.start_x = event.x
        self.start_y = event.y

    def do_resize(self, event):
        dx = event.x - self.start_x
        dy = event.y - self.start_y
        delta = max(dx, dy)
        new_size = max(min(self.width + delta, 800), 150)
        self.width = new_size
        self.height = new_size
        self.root.geometry(f"{int(new_size)}x{int(new_size)}")
        self.canvas.config(width=new_size, height=new_size)
        settings["size"] = int(new_size)
        self.init_graphics()
        self.start_x = event.x
        self.start_y = event.y
        self.save_layout_throttled(force=True)

    def show_context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def toggle_labels(self):
        settings["show_labels"] = not settings["show_labels"]
        self.init_graphics()
        self.save_layout_throttled(force=True)

    def toggle_visual_mode(self):
        settings["visual_mode"] = "minimal" if settings["visual_mode"] == "radar" else "radar"
        self.init_graphics()
        self.save_layout_throttled(force=True)

    def test_direction(self, angle):
        global sector_data, current_peak, current_confidence, is_human
        test = build_sector_levels(angle, 1.0, spread=settings.get("sector_spread", 2))
        for i in range(16):
            sector_data[i] = max(sector_data[i], test[i])
        current_peak = 1.0
        current_confidence = 1.0
        is_human = True

    def save_layout_throttled(self, force=False):
        now = time.time()
        if not force and (now - self.last_config_save) < 0.7:
            return
        self.last_config_save = now
        saved = load_config()
        saved.update({
            "size": int(settings["size"]),
            "overlay_x": int(settings["overlay_x"]),
            "overlay_y": int(settings["overlay_y"]),
            "show_labels": settings["show_labels"],
            "visual_mode": settings["visual_mode"],
        })
        save_config(saved)

    def close(self):
        global running
        running = False
        settings["overlay_x"] = self.root.winfo_x()
        settings["overlay_y"] = self.root.winfo_y()
        self.save_layout_throttled(force=True)
        self.root.destroy()

    def draw_block(self, cx, cy, r_in, r_out, start_deg, end_deg):
        points = []
        steps = 3
        for i in range(steps + 1):
            ang = math.radians(start_deg + (end_deg - start_deg) * i / steps - 90)
            points.append(cx + r_out * math.cos(ang))
            points.append(cy + r_out * math.sin(ang))
        for i in range(steps + 1):
            ang = math.radians(end_deg - (end_deg - start_deg) * i / steps - 90)
            points.append(cx + r_in * math.cos(ang))
            points.append(cy + r_in * math.sin(ang))
        return self.canvas.create_polygon(points, outline=self.profile["grid"], width=1, fill=TRANS_COLOR)

    def init_graphics(self):
        self.canvas.delete("all")
        self.blocks_gfx = []
        self.profile = COLOR_PROFILES.get(settings["color_profile"], COLOR_PROFILES["orange"])
        cx, cy = self.width / 2, self.height / 2
        radius = min(cx, cy) - 10 
        
        grid_color = self.profile["grid"]
        active_color = self.profile["active"]
        text_color = self.profile["text"]
        minimal = settings["visual_mode"] == "minimal"
        if not minimal:
            self.canvas.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, fill=TRANS_COLOR, outline=grid_color, width=2)
            self.canvas.create_oval(cx-radius*0.7, cy-radius*0.7, cx+radius*0.7, cy+radius*0.7, outline=grid_color, width=1)
            self.canvas.create_oval(cx-radius*0.4, cy-radius*0.4, cx+radius*0.4, cy+radius*0.4, outline=grid_color, width=1)
        
        num_sectors = 16
        blocks_per_sector = 6 if minimal else 10
        inner_gap = radius * 0.52 if minimal else radius * 0.15
        block_depth = (radius - inner_gap) / blocks_per_sector
        sector_angle = 360 / 16
        
        for s in range(num_sectors):
            blocks = []
            for b in range(blocks_per_sector):
                r_in = inner_gap + (b * block_depth) + 1
                r_out = r_in + block_depth - 1
                center = s * sector_angle
                start = center - (sector_angle/2) + 1.5
                end = center + (sector_angle/2) - 1.5
                poly = self.draw_block(cx, cy, r_in, r_out, start, end)
                blocks.append(poly)
            self.blocks_gfx.append(blocks)
            
        font_size = int(radius / 6) if minimal else int(radius / 5)
        self.center_icon = self.canvas.create_text(cx, cy, text="▲", fill=active_color, font=("Arial", font_size))

        if settings["show_labels"]:
            label_font = ("Arial", max(int(radius / 12), 10), "bold")
            label_offset = radius * 0.82
            labels = [
                ("F", 0, -label_offset),
                ("R", label_offset, 0),
                ("B", 0, label_offset),
                ("L", -label_offset, 0),
            ]
            for text, dx, dy in labels:
                self.canvas.create_text(cx + dx, cy + dy, text=text, fill=text_color, font=label_font)

        status_font = ("Consolas", max(int(radius / 15), 9), "bold")
        self.status_text = self.canvas.create_text(cx, cy + radius * 0.34, text="IDLE", fill=text_color, font=status_font)
        self.confidence_text = self.canvas.create_text(cx, cy + radius * 0.23, text="CONF 0%", fill=text_color, font=("Consolas", max(int(radius / 20), 8), "bold"))
        self.event_text = self.canvas.create_text(cx, cy - radius * 0.29, text="EVENT IDLE", fill=text_color, font=("Consolas", max(int(radius / 18), 8), "bold"))
        bar_w = radius * 0.65
        bar_y = cy + radius * 0.48
        self.canvas.create_rectangle(cx - bar_w / 2, bar_y, cx + bar_w / 2, bar_y + 4, outline=grid_color, fill=TRANS_COLOR)
        self.peak_bar = self.canvas.create_rectangle(cx - bar_w / 2, bar_y, cx - bar_w / 2, bar_y + 4, outline="", fill=active_color)
        
        grip_size = 20
        self.resize_grip = self.canvas.create_polygon(
            self.width, self.height, self.width-grip_size, self.height, self.width, self.height-grip_size, 
            fill=active_color, outline="black"
        )
        self.canvas.tag_bind(self.resize_grip, '<Button-1>', self.start_resize)
        self.canvas.tag_bind(self.resize_grip, '<B1-Motion>', self.do_resize)
        self.canvas.tag_bind(self.resize_grip, '<Enter>', lambda e: self.root.config(cursor="sizing"))
        self.canvas.tag_bind(self.resize_grip, '<Leave>', lambda e: self.root.config(cursor="arrow"))

    def update_gui(self):
        global sector_data, is_moving, is_human, current_peak, current_confidence, current_event, audio_status
        decay = 0.08
        active_color = self.profile["active"]
        danger_color = self.profile["danger"]
        muted_color = self.profile["muted"]
        text_color = self.profile["text"]
        blocks_per_sector = 6 if settings["visual_mode"] == "minimal" else 10
        for s in range(16):
            level = sector_data[s]
            active = int(math.ceil(level * blocks_per_sector))
            for b in range(blocks_per_sector):
                poly = self.blocks_gfx[s][b]
                if b < active:
                    if current_event in ("IMPACT", "SHARP") and level > 0.65:
                        col = danger_color
                    else:
                        col = active_color
                    self.canvas.itemconfigure(poly, fill=col)
                else:
                    self.canvas.itemconfigure(poly, fill=TRANS_COLOR)
            if sector_data[s] > 0: sector_data[s] -= decay
            if sector_data[s] < 0: sector_data[s] = 0

        if audio_status == "ERROR":
            status = "AUDIO ERROR"
            icon_color = danger_color
        elif is_moving:
            status = "MOVE"
            icon_color = muted_color
        elif is_human:
            status = "LOUD"
            icon_color = danger_color
        elif current_peak > 0.05:
            status = "SOUND"
            icon_color = active_color
        else:
            status = "IDLE"
            icon_color = active_color

        self.canvas.itemconfigure(self.center_icon, fill=icon_color)
        if self.status_text:
            self.canvas.itemconfigure(self.status_text, text=status, fill=danger_color if is_human else text_color)
        if self.confidence_text:
            conf = int(clamp(current_confidence, 0.0, 1.0) * 100)
            self.canvas.itemconfigure(self.confidence_text, text=f"CONF {conf}%", fill=danger_color if conf > 80 else text_color)
        if self.event_text:
            event_color = danger_color if current_event in ("IMPACT", "SHARP") else text_color
            self.canvas.itemconfigure(self.event_text, text=f"EVENT {current_event}", fill=event_color)
        if self.peak_bar:
            cx = self.width / 2
            radius = min(self.width, self.height) / 2 - 10
            bar_w = radius * 0.65
            bar_y = self.height / 2 + radius * 0.48
            peak = clamp(current_peak, 0.0, 1.0)
            self.canvas.coords(self.peak_bar, cx - bar_w / 2, bar_y, cx - bar_w / 2 + bar_w * peak, bar_y + 4)
            self.canvas.itemconfigure(self.peak_bar, fill=danger_color if peak > 0.8 else active_color)
            current_peak *= 0.92
            current_confidence *= 0.94
        self.root.after(20, self.update_gui)

if __name__ == "__main__":
    show_launcher()
    if running:
        t = threading.Thread(target=audio_loop)
        t.daemon = True
        t.start()
        try:
            root = tk.Tk()
            app = RadarOverlay(root)
            root.mainloop()
        except Exception as e:
            log_message(f"GUI Error: {e}")
    running = False
