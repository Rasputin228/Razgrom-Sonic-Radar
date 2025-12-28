import sys
import time
import threading
import math
import traceback
import ctypes
from ctypes import wintypes
import os
import json

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
    import keyboard
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
CONFIG_FILE = "config.json"

# ЦВЕТА
TRANS_COLOR = "#000001"
COLOR_GRID = "#444444"
COLOR_ACTIVE = "#ff9900"
COLOR_DANGER = "#ff3300"

# Глобальные переменные
sector_data = [0.0] * 16
is_moving = False
is_human = False
running = True
target_window_title = ""
selected_speaker_id = None 

# --- CTYPES ---
user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

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

# --- ЛАУНЧЕР ---
def show_launcher():
    global target_window_title, selected_speaker_id
    
    # Загрузка конфига
    saved_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
        except: pass

    root = tk.Tk()
    root.title("Razgrom Config")
    root.geometry("450x400")
    root.configure(bg="#111")
    
    style = ttk.Style()
    style.theme_use('clam')
    
    tk.Label(root, text="RAZGROM RADAR v5.0", bg="#111", fg="orange", font=("Impact", 18)).pack(pady=5)

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

    tk.Label(root, text="2. Источник звука (Динамики):", bg="#111", fg="#aaa").pack(anchor="w", padx=15, pady=(10,0))
    list_aud = tk.Listbox(root, bg="#222", fg="white", height=4, selectbackground="orange", exportselection=False)
    list_aud.pack(fill="x", padx=15)
    
    speakers = []
    try:
        speakers = sc.all_speakers()
        for i, s in enumerate(speakers):
            list_aud.insert(tk.END, s.name)
            # Автовыбор сохраненного звука
            if saved_config.get("audio") == s.name:
                list_aud.selection_set(i)
                list_aud.activate(i)
    except: 
        list_aud.insert(tk.END, "Default Speakers")

    def on_start():
        global target_window_title, selected_speaker_id
        
        # Получаем данные
        try: target_window_title = list_win.get(list_win.curselection())
        except: target_window_title = ""
        
        try: selected_speaker_id = speakers[list_aud.curselection()[0]].name
        except: selected_speaker_id = None
        
        # Сохраняем конфиг
        new_config = {"window": target_window_title, "audio": selected_speaker_id}
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(new_config, f, ensure_ascii=False)
        except: pass
        
        root.destroy()

    def on_close(): sys.exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    tk.Button(root, text="ЗАПУСТИТЬ", bg="orange", fg="black", font=("Arial", 12, "bold"), command=on_start).pack(pady=15, fill="x", padx=50)
    root.mainloop()

# --- АУДИО ДВИЖОК ---
def audio_loop():
    global sector_data, is_moving, is_human, running
    
    try: np.fromstring(b'\x00'*4, dtype=np.float32)
    except:
        def fromstring_patch(string, dtype=float, count=-1, sep=''):
            if sep == '': return np.frombuffer(string, dtype=dtype, count=count)
            return np.fromiter(string.split(sep), dtype=dtype)
        np.fromstring = fromstring_patch

    try: b, a = signal.butter(4, [FREQ_LOW, FREQ_HIGH], btype='band', fs=SAMPLE_RATE)
    except: return

    mic = None
    try:
        if selected_speaker_id: mic = sc.get_microphone(id=str(selected_speaker_id), include_loopback=True)
        else: mic = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
    except: mic = sc.default_microphone()

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
                        time.sleep(0.2)
                        continue
                except: pass

            is_moving = False
            try:
                if keyboard.is_pressed('w') or keyboard.is_pressed('a') or keyboard.is_pressed('s') or keyboard.is_pressed('d'):
                    is_moving = True
            except: pass

            filtered = signal.lfilter(b, a, data, axis=0)
            raw_l = filtered[:, 0]
            raw_r = filtered[:, 1]
            
            suppress = 0.9 if is_moving else 0.5
            side_l = np.maximum(raw_l - (raw_r * suppress), 0)
            side_r = np.maximum(raw_r - (raw_l * suppress), 0)
            
            vol_l = np.power(np.sqrt(np.mean(side_l**2)) * SENSITIVITY, COMPRESSION)
            vol_r = np.power(np.sqrt(np.mean(side_r**2)) * SENSITIVITY, COMPRESSION)
            
            if is_moving:
                vol_l *= 0.4
                vol_r *= 0.4

            total = vol_l + vol_r
            
            is_back = False
            if total > 0.05:
                freqs = np.fft.rfft(data[:, 0] + data[:, 1])
                mags = np.abs(freqs)
                if np.sum(mags) > 0:
                    centroid = (np.sum(np.arange(len(mags)) * mags) / np.sum(mags)) * (SAMPLE_RATE / BLOCK_SIZE)
                    if centroid < REAR_THRESHOLD: is_back = True

            if total > 0.02:
                balance = (vol_r - vol_l) / (total + 0.0001)
                angle = balance * 90 
                base = 8 if is_back else 0
                offset = (angle / 90) * 4
                idx = int(base + offset) % 16
                val = min(total, 1.0)
                
                target = [0.0] * 16
                target[idx] = val
                target[(idx-1)%16] = val * 0.5
                target[(idx+1)%16] = val * 0.5

                for i in range(16):
                    if target[i] > sector_data[i]: sector_data[i] = target[i]
            
            is_human = True if total > 0.6 else False

# --- GUI ---
class RadarOverlay:
    def __init__(self, root):
        self.root = root
        self.root.title("Razgrom Overlay")
        self.root.overrideredirect(True)
        self.width = 300
        self.height = 300
        self.root.geometry(f"{self.width}x{self.height}+100+100")
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", TRANS_COLOR)
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg=TRANS_COLOR, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind('<Button-1>', self.start_move)
        self.canvas.bind('<B1-Motion>', self.do_move)
        
        self.start_x = 0
        self.start_y = 0
        self.blocks_gfx = [] 
        self.init_graphics()
        self.update_gui()

    def start_move(self, event):
        self.start_x = event.x
        self.start_y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + (event.x - self.start_x)
        y = self.root.winfo_y() + (event.y - self.start_y)
        self.root.geometry(f"+{x}+{y}")

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
        self.init_graphics()
        self.start_x = event.x
        self.start_y = event.y

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
        return self.canvas.create_polygon(points, outline=COLOR_GRID, width=1, fill=TRANS_COLOR)

    def init_graphics(self):
        self.canvas.delete("all")
        self.blocks_gfx = []
        cx, cy = self.width / 2, self.height / 2
        radius = min(cx, cy) - 10 
        
        self.canvas.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, fill=TRANS_COLOR, outline=COLOR_GRID, width=2)
        self.canvas.create_oval(cx-radius*0.7, cy-radius*0.7, cx+radius*0.7, cy+radius*0.7, outline=COLOR_GRID, width=1)
        self.canvas.create_oval(cx-radius*0.4, cy-radius*0.4, cx+radius*0.4, cy+radius*0.4, outline=COLOR_GRID, width=1)
        
        num_sectors = 16
        blocks_per_sector = 10
        inner_gap = radius * 0.15
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
            
        font_size = int(radius / 5)
        self.center_icon = self.canvas.create_text(cx, cy, text="▲", fill=COLOR_ACTIVE, font=("Arial", font_size))
        
        grip_size = 20
        self.resize_grip = self.canvas.create_polygon(
            self.width, self.height, self.width-grip_size, self.height, self.width, self.height-grip_size, 
            fill=COLOR_ACTIVE, outline="black"
        )
        self.canvas.tag_bind(self.resize_grip, '<Button-1>', self.start_resize)
        self.canvas.tag_bind(self.resize_grip, '<B1-Motion>', self.do_resize)
        self.canvas.tag_bind(self.resize_grip, '<Enter>', lambda e: self.root.config(cursor="sizing"))
        self.canvas.tag_bind(self.resize_grip, '<Leave>', lambda e: self.root.config(cursor="arrow"))

    def update_gui(self):
        global sector_data, is_moving
        decay = 0.08
        for s in range(16):
            level = sector_data[s]
            active = int(math.ceil(level * 10))
            for b in range(10):
                poly = self.blocks_gfx[s][b]
                if b < active:
                    col = COLOR_DANGER if level > 0.8 else COLOR_ACTIVE
                    self.canvas.itemconfigure(poly, fill=col)
                else:
                    self.canvas.itemconfigure(poly, fill=TRANS_COLOR)
            if sector_data[s] > 0: sector_data[s] -= decay
            if sector_data[s] < 0: sector_data[s] = 0

        if is_moving: self.canvas.itemconfigure(self.center_icon, fill="#443300")
        else: self.canvas.itemconfigure(self.center_icon, fill=COLOR_ACTIVE)
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