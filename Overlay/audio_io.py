import json
import math
import os
import time

import numpy as np
import soundcard as sc

from app_config import (
    BLOCK_SIZE,
    COMPRESSION,
    DIAGNOSTIC_REPORT_FILE,
    NOISE_FLOOR,
    SAMPLE_RATE,
    clamp,
    log_message,
)


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


def audio_level_from_block(data, sensitivity):
    channel_sum = math.sqrt(float(np.mean(data[:, 0] ** 2))) + math.sqrt(float(np.mean(data[:, 1] ** 2)))
    return float(np.power(channel_sum * sensitivity, COMPRESSION))


def measure_noise_floor(source, sensitivity, seconds=3.0):
    levels = []
    frames = max(1, int(seconds * SAMPLE_RATE / BLOCK_SIZE))
    with open_audio_recorder_source(source).recorder(samplerate=SAMPLE_RATE, channels=2, blocksize=BLOCK_SIZE) as recorder:
        for _ in range(frames):
            data = recorder.record(numframes=BLOCK_SIZE)
            levels.append(audio_level_from_block(data, sensitivity))

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


def preflight_audio_source(source, sensitivity, noise_floor):
    report = diagnose_audio_source(source, sensitivity, seconds=1.0)
    warnings = []

    if report["frames"] <= 0:
        return False, ["Источник не вернул аудиокадры."], report

    if report["peak"] <= max(noise_floor * 1.15, 0.01):
        warnings.append("Сигнал почти нулевой. Проверьте, что игра выводит звук на выбранный источник.")

    if abs(report["balance"]) > 0.85:
        warnings.append("Сильный перекос каналов. Возможно, выбран моно/битый источник или перепутан маршрут.")

    return True, warnings, report


def write_diagnostic_report(window, audio_source, settings, audio_status, audio_error_message, last_report=None):
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
