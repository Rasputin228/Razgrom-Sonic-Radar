import sys
import time
import threading
import math
import traceback

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
except Exception as e:
    log_message(f"Import Error: {e}")
    sys.exit(1)

# --- НАСТРОЙКИ АУДИО ---
SAMPLE_RATE = 48000
BLOCK_SIZE = 1024
FREQ_LOW = 50
FREQ_HIGH = 450
SENSITIVITY = 350.0
SUPPRESSION_MOVE = 0.85
SUPPRESSION_IDLE = 0.6

# Глобальные переменные
sector_levels = [0.0] * 8
is_moving = False
is_human = False
running = True

# --- АУДИО ДВИЖОК ---
def audio_loop():
    global sector_levels, is_moving, is_human, running
    
    # Патч Numpy
    try: np.fromstring(b'\x00'*4, dtype=np.float32)
    except:
        def fromstring_patch(string, dtype=float, count=-1, sep=''):
            if sep == '': return np.frombuffer(string, dtype=dtype, count=count)
            return np.fromiter(string.split(sep), dtype=dtype)
        np.fromstring = fromstring_patch

    try:
        b, a = signal.butter(4, [FREQ_LOW, FREQ_HIGH], btype='band', fs=SAMPLE_RATE)
    except: return

    while running:
        try:
            default_speaker = sc.default_speaker()
            try: mic = sc.get_microphone(id=str(default_speaker.name), include_loopback=True)
            except: mic = sc.default_microphone()

            with mic.recorder(samplerate=SAMPLE_RATE, channels=2, blocksize=BLOCK_SIZE) as recorder:
                while running:
                    data = recorder.record(numframes=BLOCK_SIZE)
                    
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
                    
                    if total > 0.05:
                        balance = (vol_r - vol_l) / (total + 0.0001)
                        val = min(total, 1.0)
                        
                        target_sectors = [0.0] * 8
                        # Sonic Logic: 0=F, 1=FR, 2=R...
                        if balance > 0.6: target_sectors[2] = val
                        elif balance > 0.2: target_sectors[1] = val
                        elif balance < -0.6: target_sectors[6] = val
                        elif balance < -0.2: target_sectors[7] = val
                        else:
                            if not is_moving: target_sectors[0] = val
                            if not is_moving: target_sectors[4] = val * 0.3

                        for i in range(8):
                            if target_sectors[i] > sector_levels[i]:
                                sector_levels[i] = target_sectors[i]
                    
                    # Детектор (упрощенный)
                    if total > 0.5: is_human = True
                    else: is_human = False

        except: time.sleep(1)

# --- GUI (SONIC PRO DESIGN) ---
class RadarOverlay:
    def __init__(self, root):
        self.root = root
        self.root.title("Razgrom Overlay")
        
        # Настройки окна
        self.root.overrideredirect(True)
        self.root.geometry("350x350+100+100")
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", "#010101")
        
        # Холст
        self.width = 350
        self.height = 350
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="#010101", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # Перемещение (ЛКМ)
        self.canvas.bind('<Button-1>', self.start_move)
        self.canvas.bind('<B1-Motion>', self.do_move)
        
        # Ресайз (ПКМ в углу)
        self.resize_grip = self.canvas.create_polygon(0,0,0,0, fill="#ff9900", outline="black")
        self.canvas.tag_bind(self.resize_grip, '<Button-1>', self.start_resize)
        self.canvas.tag_bind(self.resize_grip, '<B1-Motion>', self.do_resize)
        
        self.start_x = 0
        self.start_y = 0
        
        # Элементы радара
        self.grid_items = []
        self.sector_blocks = [] # Список списков блоков [сектор][блок]
        
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
        # Вычисляем новый размер
        dx = event.x - self.start_x
        dy = event.y - self.start_y
        
        # Сохраняем квадратные пропорции
        new_size = max(self.width + dx, 200) # Минимум 200px
        
        self.width = new_size
        self.height = new_size
        self.root.geometry(f"{int(new_size)}x{int(new_size)}")
        self.canvas.config(width=new_size, height=new_size)
        
        # Перерисовываем всё
        self.init_graphics()
        self.start_x = event.x
        self.start_y = event.y

    def draw_arc_block(self, cx, cy, r_in, r_out, start_deg, end_deg, tags):
        # Рисует сегмент кольца (блок)
        points = []
        
        # Внешняя дуга
        steps = 4
        for i in range(steps + 1):
            ang = math.radians(start_deg + (end_deg - start_deg) * i / steps - 90)
            points.append(cx + r_out * math.cos(ang))
            points.append(cy + r_out * math.sin(ang))
            
        # Внутренняя дуга (в обратном порядке)
        for i in range(steps + 1):
            ang = math.radians(end_deg - (end_deg - start_deg) * i / steps - 90)
            points.append(cx + r_in * math.cos(ang))
            points.append(cy + r_in * math.sin(ang))
            
        return self.canvas.create_polygon(points, tags=tags, outline="black", width=1, fill="")

    def init_graphics(self):
        self.canvas.delete("all")
        self.sector_blocks = []
        
        cx, cy = self.width / 2, self.height / 2
        radius = min(cx, cy) - 20 # Отступ
        
        # 1. Фон и Сетка
        self.canvas.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, outline="#553300", width=2)
        self.canvas.create_oval(cx-radius*0.66, cy-radius*0.66, cx+radius*0.66, cy+radius*0.66, outline="#553300", width=1, dash=(4,4))
        self.canvas.create_oval(cx-radius*0.33, cy-radius*0.33, cx+radius*0.33, cy+radius*0.33, outline="#553300", width=1, dash=(4,4))
        
        # 2. Сектора (Блоки)
        num_sectors = 8
        blocks_per_sector = 5
        inner_gap = 30
        block_depth = (radius - inner_gap) / blocks_per_sector
        
        for s in range(num_sectors):
            blocks = []
            for b in range(blocks_per_sector):
                r_in = inner_gap + (b * block_depth) + 2
                r_out = r_in + block_depth - 4
                
                # Углы: Сектор 0 это верх (-22.5 до +22.5)
                start_angle = (s * 45) - 20
                end_angle = (s * 45) + 20
                
                # Рисуем блок (по умолчанию невидимый/прозрачный)
                poly = self.draw_arc_block(cx, cy, r_in, r_out, start_angle, end_angle, tags=f"s{s}b{b}")
                self.canvas.itemconfigure(poly, fill="", state='hidden')
                blocks.append(poly)
            self.sector_blocks.append(blocks)
            
        # 3. Центр
        self.center_icon = self.canvas.create_text(cx, cy, text="▲", fill="#ff9900", font=("Arial", int(radius/10)))
        
        # 4. Ресайз грип (Треугольник в углу)
        self.resize_grip = self.canvas.create_polygon(
            self.width, self.height, 
            self.width-20, self.height, 
            self.width, self.height-20, 
            fill="#ff9900", outline="black"
        )
        self.canvas.tag_bind(self.resize_grip, '<Button-1>', self.start_resize)
        self.canvas.tag_bind(self.resize_grip, '<B1-Motion>', self.do_resize)

    def update_gui(self):
        global sector_levels, is_moving, is_human
        decay = 0.05
        
        for s in range(8):
            level = sector_levels[s]
            
            # Сколько блоков зажечь? (0..5)
            active_count = int(math.ceil(level * 5))
            
            for b in range(5):
                poly = self.sector_blocks[s][b]
                
                if b < active_count:
                    # Активен
                    self.canvas.itemconfigure(poly, state='normal')
                    
                    # Цвет
                    color = "#ff9900" # Оранжевый
                    if level > 0.8: color = "#ff3300" # Красный
                    
                    # Прозрачность (симуляция через stipple)
                    stipple = "" # Сплошной
                    if b >= active_count - 1: stipple = "gray75" # Самый дальний блок полупрозрачный
                    
                    self.canvas.itemconfigure(poly, fill=color, stipple=stipple)
                else:
                    # Выключен
                    self.canvas.itemconfigure(poly, state='hidden')
            
            # Затухание
            if sector_levels[s] > 0: sector_levels[s] -= decay
            if sector_levels[s] < 0: sector_levels[s] = 0

        # Статус центра
        if is_moving: self.canvas.itemconfigure(self.center_icon, fill="#553300")
        elif is_human: self.canvas.itemconfigure(self.center_icon, fill="red")
        else: self.canvas.itemconfigure(self.center_icon, fill="#ff9900")

        self.root.after(30, self.update_gui)

if __name__ == "__main__":
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