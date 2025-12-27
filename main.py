import time
import threading
import logging
import socket
import math
import os
import sys

# --- FIX: NUMPY VERSION PATCH ---
import numpy as np
try:
    np.fromstring(b'\x00'*4, dtype=np.float32)
except (ValueError, Exception):
    def fromstring_patch(string, dtype=float, count=-1, sep=''):
        if sep == '':
            return np.frombuffer(string, dtype=dtype, count=count)
        return np.fromiter(string.split(sep), dtype=dtype)
    np.fromstring = fromstring_patch
# --------------------------------

import soundcard as sc
from scipy import signal
from flask import Flask, render_template_string
from flask_socketio import SocketIO
import keyboard 

# --- НАСТРОЙКИ RAZGROM PRO ---
SAMPLE_RATE = 48000
BLOCK_SIZE = 1024       
FREQ_LOW = 50           
FREQ_HIGH = 450         
SENSITIVITY = 350.0     
SUPPRESSION_MOVE = 0.85 # Глушить центр при ходьбе
SUPPRESSION_IDLE = 0.6  # Глушить центр когда стоим

# Отключаем мусор в консоли
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- ИНТЕРФЕЙС SONIC RADAR PRO (ORANGE SEGMENTS) ---
HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Sonic Radar Pro</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body { 
            background-color: #000; 
            margin: 0; 
            overflow: hidden; 
            display: flex; flex-direction: column; align-items: center; justify-content: center; 
            height: 100vh; 
            font-family: 'Segoe UI', sans-serif;
            color: #ff9900; 
            user-select: none;
        }
        
        /* КОРПУС РАДАРА */
        #radar-case {
            position: relative;
            width: 360px; height: 360px;
            background: radial-gradient(circle, #1a1000 30%, #000000 80%);
            border-radius: 50%;
            /* Текстура сетки на фоне */
            background-image: 
                linear-gradient(rgba(50, 30, 0, 0.3) 1px, transparent 1px),
                linear-gradient(90deg, rgba(50, 30, 0, 0.3) 1px, transparent 1px);
            background-size: 20px 20px;
            box-shadow: 0 0 50px rgba(255, 140, 0, 0.1);
            border: 1px solid #332200;
        }

        /* КРУГИ РАЗМЕТКИ */
        .ring {
            position: absolute; top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            border: 1px solid #664400;
            border-radius: 50%;
            opacity: 0.6;
            box-sizing: border-box;
        }
        .r1 { width: 25%; height: 25%; border-width: 2px; border-color: #ff9900; opacity: 0.8; }
        .r2 { width: 50%; height: 50%; border-style: dashed; }
        .r3 { width: 75%; height: 75%; }
        .r4 { width: 98%; height: 98%; border: 2px solid #885500; }

        /* МЕТКИ СТОРОН */
        .ticks { position: absolute; width: 100%; height: 100%; top: 0; left: 0; }
        .tick { 
            position: absolute; background: #ff9900; 
            top: 50%; left: 50%; transform-origin: 0 0;
        }
        /* 4 основных деления */
        .t-n { width: 4px; height: 15px; transform: translate(-2px, -180px); }
        .t-e { width: 15px; height: 4px; transform: translate(165px, -2px); }
        .t-s { width: 4px; height: 15px; transform: translate(-2px, 165px); }
        .t-w { width: 15px; height: 4px; transform: translate(-180px, -2px); }

        /* SVG СЕКТОРА (СЕГМЕНТЫ) */
        svg {
            position: absolute; top: 0; left: 0;
            width: 100%; height: 100%;
            transform: rotate(-90deg); /* 0 градусов = Верх */
        }

        /* Стиль сегментов */
        path {
            fill: #ff9900;
            stroke: #000;
            stroke-width: 1px;
            opacity: 0.1; /* Выключенное состояние */
            transition: opacity 0.05s linear;
        }
        
        /* Активный сегмент */
        .active-seg { opacity: 1.0; filter: drop-shadow(0 0 5px #ff9900); }
        .danger-seg { fill: #ff3300; opacity: 1.0; filter: drop-shadow(0 0 8px red); }

        /* ЦЕНТР */
        #center-hub {
            position: absolute; top: 50%; left: 50%;
            width: 40px; height: 40px;
            background: #110a00;
            border: 2px solid #ff9900;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            z-index: 10;
            display: flex; align-items: center; justify-content: center;
            font-weight: bold; font-size: 20px;
            box-shadow: 0 0 15px #ff9900;
        }

        #hud { position: absolute; bottom: 20px; text-align: center; width: 100%; }
        #status-text { 
            font-family: 'Consolas', monospace; 
            font-size: 16px; 
            color: #ff9900; 
            text-transform: uppercase; 
            letter-spacing: 2px; 
        }

    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script>
        var socket = io({transports: ['websocket'], upgrade: false});
        
        // 8 Секторов, в каждом по 5 блоков (дистанция)
        // sectors[0] = громкость сектора 0 (0.0 - 1.0)
        var sectorLevels = [0,0,0,0,0,0,0,0];
        var DECAY = 0.05;

        // Генерируем SVG сегменты программно, чтобы было ровно
        function generateSegments() {
            var svg = document.getElementById("radar-svg");
            var numSectors = 8;
            var numBlocks = 5;
            var innerRadius = 40;
            var outerRadius = 170;
            var gap = 4; // отступ между блоками
            
            var blockDepth = (outerRadius - innerRadius) / numBlocks;

            for (var s = 0; s < numSectors; s++) {
                for (var b = 0; b < numBlocks; b++) {
                    // Вычисляем радиусы для этого блока
                    var rIn = innerRadius + (b * blockDepth) + 2;
                    var rOut = rIn + blockDepth - 4;
                    
                    // Углы (в радианах)
                    // Сектор 0 (Верх) должен быть от -22.5 до +22.5 градусов
                    var startAngle = (s * 45) - 20; 
                    var endAngle = (s * 45) + 20;
                    
                    var startRad = startAngle * (Math.PI / 180);
                    var endRad = endAngle * (Math.PI / 180);

                    // Координаты точек
                    var x1 = 180 + rIn * Math.cos(startRad);
                    var y1 = 180 + rIn * Math.sin(startRad);
                    var x2 = 180 + rOut * Math.cos(startRad);
                    var y2 = 180 + rOut * Math.sin(startRad);
                    var x3 = 180 + rOut * Math.cos(endRad);
                    var y3 = 180 + rOut * Math.sin(endRad);
                    var x4 = 180 + rIn * Math.cos(endRad);
                    var y4 = 180 + rIn * Math.sin(endRad);

                    // Рисуем путь (Path)
                    var d = `M ${x1} ${y1} L ${x2} ${y2} A ${rOut} ${rOut} 0 0 1 ${x3} ${y3} L ${x4} ${y4} A ${rIn} ${rIn} 0 0 0 ${x1} ${y1} Z`;
                    
                    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
                    path.setAttribute("d", d);
                    path.setAttribute("id", `s${s}_b${b}`); // ID: s0_b0 (сектор 0, блок 0 - самый близкий)
                    svg.appendChild(path);
                }
            }
        }

        socket.on('update_pro', function(data) {
            var input = data.sectors;
            var status = document.getElementById("status-text");
            var center = document.getElementById("center-hub");

            // Обновляем уровни
            for(var i=0; i<8; i++) {
                if (input[i] > sectorLevels[i]) sectorLevels[i] = input[i];
            }

            if (data.is_moving) {
                status.innerText = "MOVING [SUPPRESSED]";
                status.style.color = "#664400";
                center.style.borderColor = "#664400";
            } else if (data.is_human) {
                status.innerText = "⚠️ HOSTILE DETECTED ⚠️";
                status.style.color = "#ff3300";
                center.style.borderColor = "#ff3300";
                center.innerText = "!";
            } else {
                status.innerText = "SONIC RADAR PRO";
                status.style.color = "#ff9900";
                center.style.borderColor = "#ff9900";
                center.innerText = "";
            }
        });

        function render() {
            for (var s = 0; s < 8; s++) {
                // Затухание уровня сектора
                if (sectorLevels[s] > 0) sectorLevels[s] -= DECAY;
                if (sectorLevels[s] < 0) sectorLevels[s] = 0;

                var level = sectorLevels[s]; // 0.0 to 1.0
                
                // Сколько блоков должно гореть? (0..5)
                var activeBlocks = Math.ceil(level * 5); 

                for (var b = 0; b < 5; b++) {
                    var el = document.getElementById(`s${s}_b${b}`);
                    if (!el) continue;

                    if (b < activeBlocks) {
                        // Блок активен
                        el.classList.add("active-seg");
                        
                        // Если очень громко - красим в красный
                        if (level > 0.85) el.classList.add("danger-seg");
                        else el.classList.remove("danger-seg");
                        
                    } else {
                        // Блок выключен
                        el.classList.remove("active-seg");
                        el.classList.remove("danger-seg");
                    }
                }
            }
            requestAnimationFrame(render);
        }

        window.onload = function() {
            generateSegments();
            render();
        };
    </script>
</head>
<body>
    <div id="radar-case">
        <!-- Сетка фона -->
        <div class="ring r1"></div>
        <div class="ring r2"></div>
        <div class="ring r3"></div>
        <div class="ring r4"></div>

        <!-- Метки -->
        <div class="ticks">
            <div class="tick t-n"></div>
            <div class="tick t-e"></div>
            <div class="tick t-s"></div>
            <div class="tick t-w"></div>
        </div>

        <!-- SVG для сегментов -->
        <svg id="radar-svg" viewBox="0 0 360 360"></svg>

        <div id="center-hub"></div>
    </div>
    
    <div id="hud">
        <div id="status-text">INITIALIZING...</div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

def audio_engine():
    print(">>> [RAZGROM] SONIC PRO ENGINE: STARTED")
    
    b, a = signal.butter(4, [FREQ_LOW, FREQ_HIGH], btype='band', fs=SAMPLE_RATE)
    
    last_step = 0
    intervals = []

    while True:
        try:
            default_speaker = sc.default_speaker()
            try:
                mic = sc.get_microphone(id=str(default_speaker.name), include_loopback=True)
                print(f">>> DRIVER HOOK: {mic.name}")
            except:
                mic = sc.default_microphone()

            with mic.recorder(samplerate=SAMPLE_RATE, channels=2, blocksize=BLOCK_SIZE) as recorder:
                while True:
                    data = recorder.record(numframes=BLOCK_SIZE)
                    
                    # 1. Движение
                    is_moving = False
                    try:
                        if keyboard.is_pressed('w') or keyboard.is_pressed('a') or keyboard.is_pressed('s') or keyboard.is_pressed('d'):
                            is_moving = True
                    except: pass

                    # 2. Фильтр
                    filtered = signal.lfilter(b, a, data, axis=0)
                    raw_l = filtered[:, 0]
                    raw_r = filtered[:, 1]
                    
                    # 3. Подавление центра (Mid-Side)
                    suppression = SUPPRESSION_MOVE if is_moving else SUPPRESSION_IDLE
                    side_l = raw_l - (raw_r * suppression)
                    side_r = raw_r - (raw_l * suppression)
                    side_l = np.maximum(side_l, 0)
                    side_r = np.maximum(side_r, 0)
                    
                    vol_l = np.sqrt(np.mean(side_l**2)) * SENSITIVITY
                    vol_r = np.sqrt(np.mean(side_r**2)) * SENSITIVITY
                    
                    if is_moving:
                        vol_l *= 0.5
                        vol_r *= 0.5

                    total = vol_l + vol_r
                    sectors = [0.0] * 8
                    
                    if total > 0.05:
                        # Баланс: -1 (Лево) ... 1 (Право)
                        balance = (vol_r - vol_l) / (total + 0.0001)
                        val = min(total, 1.0)
                        
                        # --- ЖЕСТКАЯ ПРИВЯЗКА СЕКТОРОВ (FIX КАСАТЕЛЬНОЙ) ---
                        # Sonic Radar Logic:
                        # 0:F, 1:FR, 2:R, 3:BR, 4:B, 5:BL, 6:L, 7:FL
                        
                        if balance > 0.6: 
                            sectors[2] = val;    # ЧИСТО ПРАВО (3 часа)
                        elif balance > 0.2: 
                            sectors[1] = val;  # ПРАВО-ВЕРХ (1.5 часа)
                        elif balance < -0.6: 
                            sectors[6] = val; # ЧИСТО ЛЕВО (9 часов)
                        elif balance < -0.2: 
                            sectors[7] = val; # ЛЕВО-ВЕРХ (10.5 часов)
                        else:
                            # ЦЕНТР
                            if not is_moving: sectors[0] = val; 
                            
                            # Немного подсвечиваем задние сектора для объема (зеркало)
                            if not is_moving: sectors[4] = val * 0.3; 

                    # Детектор Врага
                    is_human = False
                    now = time.time()
                    if total > 0.25 and (now - last_step) > 0.2:
                        dt = now - last_step
                        last_step = now
                        if dt < 1.0:
                            intervals.append(dt)
                            if len(intervals) > 5: intervals.pop(0)
                            if len(intervals) >= 3 and np.var(intervals) > 0.04:
                                is_human = True

                    socketio.emit('update_pro', {
                        'sectors': sectors,
                        'is_moving': is_moving,
                        'is_human': is_human
                    })
                    
                    socketio.sleep(0.01)

        except Exception as e:
            print(f">>> ERROR: {e}")
            time.sleep(3)

if __name__ == '__main__':
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    port = 5555 
    
    print("\n=============================================")
    print("      SONIC RADAR PRO: RAZGROM EDITION       ")
    print("=============================================")
    print(f" 1. Connect Phone to Wi-Fi")
    print(f" 2. Open: http://{local_ip}:{port}")
    print("=============================================\n")
    
    t = threading.Thread(target=audio_engine)
    t.daemon = True
    t.start()
    
    try:
        socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
    except:
        pass