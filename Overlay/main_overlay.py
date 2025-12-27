import sys
import time
import threading
import math
import traceback
import os

# --- ЛОГГЕР ---
def log_message(msg):
    try:
        with open("overlay_debug.txt", "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except: pass

def handle_exception(exc_type, exc_value, exc_traceback):
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    log_message(f"CRITICAL ERROR:\n{error_msg}")
    sys.exit(1)

sys.excepthook = handle_exception

try:
    import tkinter as tk
    import numpy as np
    import soundcard as sc
    from scipy import signal
    import keyboard
    import ctypes # Для проверки активного окна
except Exception as e:
    log_message(f"Import Error: {e}")
    sys.exit(1)

# --- НАСТРОЙКИ ---
SAMPLE_RATE = 48000
BLOCK_SIZE = 1024
FREQ_LOW = 50
FREQ_HIGH = 4500
SENSITIVITY = 350.0
SUPPRESSION_MOVE = 0.85
SUPPRESSION_IDLE = 0.6
REAR_FREQ_THRESHOLD = 1500

# Глобальные переменные
sector_levels = [0.0] * 8
is_moving = False
is_human = False
running = True
target_window_active = True # Флаг: активно ли окно игры

# --- SMART CONFIG (Сохранение устройства) ---
CONFIG_FILE = "device_config.txt"

def get_audio_device():
    print("\n--- 🔊 НАСТРОЙКА ЗВУКА ---")
    speakers = sc.all_speakers()
    
    # 1. Если конфиг есть - читаем
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved_name = f.read().strip()
            
            # Ищем сохраненное устройство
            for sp in speakers:
                if sp.name == saved_name:
                    print(f">>> Загружено сохраненное устройство: {sp.name}")
                    print(">>> (Чтобы сбросить, удалите файл device_config.txt)")
                    return sc.get_microphone(id=str(sp.name), include_loopback=True)
        except:
            print("Ошибка чтения конфига. Сброс.")

    # 2. Если конфига нет - спрашиваем
    print("Доступные устройства:")
    for i, sp in enumerate(speakers):
        print(f"[{i}] {sp.name}")
    
    print("\nСОВЕТ: Чтобы радар слышал ТОЛЬКО игру, используйте VB-Cable.")
    print("Введите номер устройства (или Enter для стандартного):")
    choice = input("> ")
    
    selected_mic = sc.default_microphone()
    
    if choice.strip().isdigit():
        idx = int(choice)
        if 0 <= idx < len(speakers):
            target = speakers[idx]
            print(f">>> Выбрано: {target.name}")
            # Сохраняем выбор
            with open(CONFIG_FILE, "w") as f:
                f.write(target.name)
            try:
                selected_mic = sc.get_microphone(id=str(target.name), include_loopback=True)
            except:
                print("Не удалось подключиться к Loopback. Использую Default.")
    
    return selected_mic

# --- WINDOW WATCHER (Следит за окном) ---
def check_active_window():
    global target_window_active
    user32 = ctypes.windll.user32
    while running:
        try:
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            window_title = buff.value
            
            # Если мы в оверлее или в игре - работаем
            # Если мы свернулись в браузер - спим
            # Пустой заголовок часто бывает у оверлеев
            if "Arena" in window_title or "Razgrom" in window_title or window_title == "":
                target_window_active = True
            else:
                # Если мы просто на рабочем столе или в браузере - выключаем анализ
                # (Чтобы музыка из ВК не дергала радар, пока мы альт-табнулись)
                target_window_active = False
                
        except: pass
        time.sleep(1.0)

# --- АУДИО ДВИЖОК ---
def audio_loop(mic):
    global sector_levels, is_moving, is_human, running, target_window_active
    
    try: np.fromstring(b'\x00'*4, dtype=np.float32)
    except:
        def fromstring_patch(string, dtype=float, count=-1, sep=''):
            if sep == '': return np.frombuffer(string, dtype=dtype, count=count)
            return np.fromiter(string.split(sep), dtype=dtype)
        np.fromstring = fromstring_patch

    b, a = signal.butter(4, [FREQ_LOW, FREQ_HIGH], btype='band', fs=SAMPLE_RATE)
    last_step = 0
    intervals = []

    with mic.recorder(samplerate=SAMPLE_RATE, channels=2, blocksize=BLOCK_SIZE) as recorder:
        while running:
            data = recorder.record(numframes=BLOCK_SIZE)
            
            # Если игра свернута - не обрабатываем звук
            if not target_window_active:
                time.sleep(0.1)
                continue

            is_moving = False
            try:
                if keyboard.is_pressed('w') or keyboard.is_pressed('a') or keyboard.is_pressed('s') or keyboard.is_pressed('d'):
                    is_moving = True
            except: pass

            filtered = signal.lfilter(b, a, data, axis=0)
            raw_l = filtered[:, 0]
            raw_r = filtered[:, 1]
            
            suppression = SUPPRESSION_MOVE if is_moving else SUPPRESSION_IDLE
            side_l = np.maximum(raw_l - (raw_r * suppression), 0)
            side_r = np.maximum(raw_r - (raw_l * suppression), 0)
            
            vol_l = np.sqrt(np.mean(side_l**2)) * SENSITIVITY
            vol_r = np.sqrt(np.mean(side_r**2)) * SENSITIVITY
            
            if is_moving:
                vol_l *= 0.5
                vol_r *= 0.5

            total = vol_l + vol_r
            
            # Спектральный анализ (Сзади/Спереди)
            is_back = False
            if total > 0.05:
                freqs = np.fft.rfft(data[:, 0] + data[:, 1])
                magnitudes = np.abs(freqs)
                total_sum = np.sum(magnitudes)
                if total_sum > 0:
                    weighted_sum = np.sum(np.arange(len(magnitudes)) * magnitudes)
                    centroid = (weighted_sum / total_sum) * (SAMPLE_RATE / BLOCK_SIZE)
                    if centroid < REAR_FREQ_THRESHOLD:
                        is_back = True

            if total > 0.05:
                balance = (vol_r - vol_l) / (total + 0.0001)
                val = min(total, 1.0)
                
                target_sectors = [0.0] * 8
                # 0=F, 1=FR, 2=R, 3=BR, 4=B, 5=BL, 6=L, 7=FL
                
                if balance > 0.6: idx = 3 if is_back else 2
                elif balance > 0.2: idx = 4 if is_back else 1
                elif balance < -0.6: idx = 5 if is_back else 6
                elif balance < -0.2: idx = 4 if is_back else 7
                else: 
                    idx = 4 if is_back else 0
                    if is_moving and idx == 0: val = 0 # Не показывать центр при ходьбе

                if not is_moving or idx != 0:
                    target_sectors[idx] = val

                for i in range(8):
                    if target_sectors[i] > sector_levels[i]:
                        sector_levels[i] = target_sectors[i]
            
            # Детектор
            now = time.time()
            if total > 0.3 and (now - last_step) > 0.2:
                dt = now - last_step
                last_step = now
                if dt < 1.0:
                    intervals.append(dt)
                    if len(intervals) > 5: intervals.pop(0)
                    if len(intervals) >= 3 and np.var(intervals) > 0.04:
                        is_human = True
                    else: is_human = False

# --- GUI ---
class RadarOverlay:
    def __init__(self, root):
        self.root = root
        self.root.title("Razgrom Overlay")
        self.root.overrideredirect(True)
        self.root.geometry("350x350+100+100")
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", "#010101")
        
        self.width = 350
        self.height = 350
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#010101", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        self.canvas.bind('<Button-1>', self.start_move)
        self.canvas.bind('<B1-Motion>', self.do_move)
        
        self.start_x = 0
        self.start_y = 0
        self.sector_blocks = [] 
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

    def draw_arc_block(self, cx, cy, r_in, r_out, start_deg, end_deg, tags):
        points = []
        steps = 4
        for i in range(steps + 1):
            ang = math.radians(start_deg + (end_deg - start_deg) * i / steps - 90)
            points.append(cx + r_out * math.cos(ang))
            points.append(cy + r_out * math.sin(ang))
        for i in range(steps + 1):
            ang = math.radians(end_deg - (end_deg - start_deg) * i / steps - 90)
            points.append(cx + r_in * math.cos(ang))
            points.append(cy + r_in * math.sin(ang))
        return self.canvas.create_polygon(points, tags=tags, outline="black", width=1, fill="")

    def init_graphics(self):
        self.canvas.delete("all")
        self.sector_blocks = []
        cx, cy = self.width / 2, self.height / 2
        radius = min(cx, cy) - 20 
        
        self.canvas.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, outline="#553300", width=2)
        self.canvas.create_oval(cx-radius*0.66, cy-radius*0.66, cx+radius*0.66, cy+radius*0.66, outline="#553300", width=1, dash=(4,4))
        self.canvas.create_oval(cx-radius*0.33, cy-radius*0.33, cx+radius*0.33, cy+radius*0.33, outline="#553300", width=1, dash=(4,4))
        
        num_sectors = 8
        blocks_per_sector = 5
        inner_gap = radius * 0.2
        block_depth = (radius - inner_gap) / blocks_per_sector
        
        for s in range(num_sectors):
            blocks = []
            for b in range(blocks_per_sector):
                r_in = inner_gap + (b * block_depth) + 2
                r_out = r_in + block_depth - 2
                start_angle = (s * 45) - 20
                end_angle = (s * 45) + 20
                poly = self.draw_arc_block(cx, cy, r_in, r_out, start_angle, end_angle, tags=f"s{s}b{b}")
                self.canvas.itemconfigure(poly, fill="", state='hidden')
                blocks.append(poly)
            self.sector_blocks.append(blocks)
            
        font_size = int(radius / 5)
        self.center_icon = self.canvas.create_text(cx, cy, text="▲", fill="#ff9900", font=("Arial", font_size))
        
        grip_size = 20
        self.resize_grip = self.canvas.create_polygon(
            self.width, self.height, self.width-grip_size, self.height, self.width, self.height-grip_size, 
            fill="#ff9900", outline="black"
        )
        self.canvas.tag_bind(self.resize_grip, '<Button-1>', self.start_resize)
        self.canvas.tag_bind(self.resize_grip, '<B1-Motion>', self.do_resize)
        self.canvas.tag_bind(self.resize_grip, '<Enter>', lambda e: self.root.config(cursor="sizing"))
        self.canvas.tag_bind(self.resize_grip, '<Leave>', lambda e: self.root.config(cursor="arrow"))

    def update_gui(self):
        global sector_levels, is_moving, is_human, target_window_active
        decay = 0.05
        
        # Если окно не активно - затемняем радар
        if not target_window_active:
             self.canvas.itemconfigure(self.center_icon, text="PAUSED", font=("Arial", 10), fill="gray")
             # Гасим сектора
             for s in range(8): sector_levels[s] = 0
        else:
             self.canvas.itemconfigure(self.center_icon, text="▲", font=("Arial", int(self.width/10)))

        for s in range(8):
            level = sector_levels[s]
            active_count = int(math.ceil(level * 5))
            for b in range(5):
                poly = self.sector_blocks[s][b]
                if b < active_count:
                    self.canvas.itemconfigure(poly, state='normal')
                    color = "#ff3300" if level > 0.8 else "#ff9900"
                    stipple = "" if b < active_count - 1 else "gray75"
                    self.canvas.itemconfigure(poly, fill=color, stipple=stipple)
                else:
                    self.canvas.itemconfigure(poly, state='hidden')
            if sector_levels[s] > 0: sector_levels[s] -= decay
            if sector_levels[s] < 0: sector_levels[s] = 0

        if target_window_active:
            if is_moving: self.canvas.itemconfigure(self.center_icon, fill="#553300")
            elif is_human: self.canvas.itemconfigure(self.center_icon, fill="red")
            else: self.canvas.itemconfigure(self.center_icon, fill="#ff9900")

        self.root.after(30, self.update_gui)

if __name__ == "__main__":
    # 1. Выбор устройства (С сохранением)
    mic = get_audio_device()
    
    # 2. Запуск слежения за окном
    t_win = threading.Thread(target=check_active_window)
    t_win.daemon = True
    t_win.start()

    # 3. Запуск аудио
    t_audio = threading.Thread(target=audio_loop, args=(mic,))
    t_audio.daemon = True
    t_audio.start()
    
    try:
        root = tk.Tk()
        app = RadarOverlay(root)
        root.mainloop()
    except Exception as e:
        log_message(f"GUI Error: {e}")
    
    running = False