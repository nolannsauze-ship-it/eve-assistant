# E.V.E. — Assistant personnel Windows (v4 — fichier unique, sans Ollama)
#
# UN SEUL FICHIER : double-clique sur eve_ia.py (Python doit être installé,
# coche « Add python.exe to PATH »). Au premier lancement, E.V.E. :
#   1. installe seule ses composants (1 à 2 minutes, fenêtre noire visible),
#   2. crée un raccourci « E.V.E. » sur ton Bureau,
#   3. se relance sans fenêtre noire.
# Ensuite, lance-la depuis le raccourci du Bureau.
#
# Fonctions : discussion IA (gratuite, sans Ollama), voix, « hey EVE » / « ok EVE »,
# météo, satellites (ISS, astronautes, nuages), état/température du PC, rappels,
# ouverture d'applis, lumières wifi, contrôle ponctuel du PC (souris/clavier).
#
# Réglages (ville, lumières, applis, clé IA) : bouton « Config » = eve_config.json.
# ARRÊT D'URGENCE du contrôle PC : bouge la souris dans le coin haut-gauche de l'écran.

import os
import sys
import json
import re
import time
import queue
import socket
import colorsys
import difflib
import threading
import subprocess
import traceback
import unicodedata
import urllib.parse
import webbrowser
import importlib.util
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent


def _hidden():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# ======================================================== Installation automatique
def _bootstrap():
    """Installe les composants manquants (une seule fois)."""
    if "--gui" in sys.argv and "--install" not in sys.argv:
        pass  # relancé sans console : on vérifie quand même, mais sans bruit
    need = {
        "requests": "requests", "customtkinter": "customtkinter", "pyttsx3": "pyttsx3",
        "psutil": "psutil", "speech_recognition": "SpeechRecognition",
        "pyautogui": "pyautogui", "PIL": "pillow",
    }
    missing = [pkg for mod, pkg in need.items() if importlib.util.find_spec(mod) is None]
    if missing:
        print("\n  E.V.E. — première installation des composants (1 à 2 minutes)…\n")
        subprocess.call([sys.executable, "-m", "pip", "install", "--quiet", *missing])
    flag = BASE_DIR / ".eve_audio_tried"
    if importlib.util.find_spec("pyaudio") is None and not flag.exists():
        print("  Installation du micro (PyAudio)…")
        code = subprocess.call([sys.executable, "-m", "pip", "install", "--quiet", "pyaudio"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            flag.write_text("1")
        except Exception:
            pass
        if code != 0:
            print("  [i] Micro non installé : le texte et la voix fonctionnent quand même.")


def _ensure_shortcut():
    """Crée un raccourci « E.V.E. » sur le Bureau (une seule fois)."""
    if os.name != "nt":
        return
    marker = BASE_DIR / ".eve_shortcut"
    if marker.exists():
        return
    pyw = Path(sys.executable).with_name("pythonw.exe")
    target = pyw if pyw.exists() else Path(sys.executable)
    script = Path(__file__).resolve()

    def q(p):
        return str(p).replace("'", "''")
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'E.V.E..lnk'));"
        f"$s.TargetPath='{q(target)}';$s.Arguments='\"{q(script)}\" --gui';"
        f"$s.WorkingDirectory='{q(BASE_DIR)}';$s.Description='E.V.E. Assistant personnel';$s.Save()"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, timeout=25, creationflags=_hidden())
        if r.returncode == 0:
            marker.write_text("1")
            print("  Raccourci « E.V.E. » créé sur ton Bureau.")
    except Exception:
        pass


def _relaunch_windowless():
    """Relance l'appli sans fenêtre noire (pythonw) puis ferme la console."""
    if os.name != "nt" or "--gui" in sys.argv or "--console" in sys.argv:
        return
    exe = Path(sys.executable)
    if exe.name.lower() != "python.exe":
        return
    pyw = exe.with_name("pythonw.exe")
    if not pyw.exists():
        return
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    subprocess.Popen([str(pyw), str(Path(__file__).resolve()), "--gui", *sys.argv[1:]],
                     cwd=str(BASE_DIR), creationflags=flags, close_fds=True)
    sys.exit(0)


if __name__ == "__main__":
    try:
        _bootstrap()
        _ensure_shortcut()
    except Exception:
        pass
    _relaunch_windowless()


import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
    USE_CTK = True
except Exception:
    ctk = None
    USE_CTK = False

try:
    import requests
except Exception:
    requests = None

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

try:
    import speech_recognition as sr
except Exception:
    sr = None

try:
    import psutil
except Exception:
    psutil = None

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.15
    USE_PYAUTOGUI = True
except Exception:
    pyautogui = None
    USE_PYAUTOGUI = False


# ==================================================================== Réglages
APP_NAME = "E.V.E. | Assistant personnel"
CONFIG_PATH = BASE_DIR / "eve_config.json"
REMINDERS_PATH = BASE_DIR / "eve_rappels.json"
LOG_PATH = BASE_DIR / "eve_erreur.log"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
FREE_AI_URL = "https://text.pollinations.ai/openai"

SYSTEM_PROMPT = (
    "Tu es E.V.E., un assistant personnel utile, prudent et chaleureux. "
    "Tu réponds en français, de façon claire et concise. "
    "Tu n'affirmes jamais avoir effectué une action si tu ne l'as pas réellement faite. "
    "L'application qui t'héberge détecte elle-même, avant toi, les commandes : lumières wifi, "
    "météo, satellites, température du PC, rappels, ouverture d'applis et contrôle ponctuel du PC. "
    "Si l'utilisateur veut l'une de ces actions, invite-le à la formuler simplement "
    "(exemple : « allume les lumières », « météo à Paris »)."
)

WAKE_SEARCH = re.compile(r"\b(?:hey|hei|he|ok|okay|okey)\s*,?\s*(?:eve|yves|eva|ive)\b")
WAKE_REPLY = (
    "Oui, je suis là ! Je peux allumer les lumières de chez toi en wifi. "
    "Je peux aussi te donner la météo et les données satellites, surveiller le PC, "
    "ouvrir tes applis, te faire des rappels, et prendre le contrôle de ton PC "
    "le temps d'une tâche précise."
)

HELP_TEXT = (
    "Voici ce que je sais faire :\n"
    "• « allume / éteins les lumières », « lumières à 50 % », « lumières en rouge »\n"
    "• « météo », « météo à Paris », « météo demain »\n"
    "• « où est l'ISS », « astronautes dans l'espace », « image satellite », « prochain survol ISS »\n"
    "• « température du PC », « état du PC », « composants du PC »\n"
    "• « rappelle-moi dans 10 minutes de sortir le linge », « rappelle-moi à 18h30 d'appeler Paul », « mes rappels »\n"
    "• « ouvre Spotify », « lance Word », « ouvre YouTube »\n"
    "• « recherche sur internet … »\n"
    "• Contrôle du PC (ponctuel, il s'arrête dès que c'est fini) :\n"
    "    « prends le contrôle et ouvre le bloc-notes »,\n"
    "    « prends le contrôle et ouvre le bloc-notes et tape bonjour »,\n"
    "    « tape à ma place : bonjour tout le monde », « fais une capture d'écran »\n"
    "    Arrêt d'urgence : souris dans le coin haut-gauche de l'écran.\n"
    "• Dis « hey EVE » ou « ok EVE » (bouton Écoute permanente).\n"
    "• Bouton 🌐 Web : la même EVE dans ton navigateur (micro et voix inclus).\n\n"
    "IA : gratuite et sans Ollama. Pour de meilleures réponses, crée une clé gratuite sur "
    "console.groq.com et mets-la dans Config (groq_api_key)."
)

DEFAULT_CONFIG = {
    "ville": "Marseille",
    "lumieres": {
        "type": "aucune",
        "ips": [],
        "hue_bridge_ip": "",
        "hue_user": "",
        "ha_url": "http://homeassistant.local:8123",
        "ha_token": "",
        "ha_entities": [],
    },
    "apps_perso": {},
    "groq_api_key": "",
    "groq_model": "llama-3.1-8b-instant",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "web_port": 8765,
    "web_reseau": False,
    "web_token": "",
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for key, value in data.items():
                if isinstance(cfg.get(key), dict) and isinstance(value, dict):
                    cfg[key].update(value)
                else:
                    cfg[key] = value
        else:
            CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def norm(text):
    """Minuscules, sans accents, apostrophes/tirets -> espace (même longueur que l'original)."""
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[-’'`]", " ", t)


def http_json(url, **kwargs):
    if requests is None:
        raise RuntimeError("le module requests n'est pas installé")
    r = requests.get(url, timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()


# ======================================================================= IA (sans Ollama)
def _chat_completion(url, key, model, history, timeout=60):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    r = requests.post(url, headers=headers, timeout=timeout,
                      json={"model": model, "messages": history, "temperature": 0.7, "max_tokens": 1024})
    if not r.ok:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:120].strip()}")
    content = r.json()["choices"][0]["message"]["content"].strip()
    if not content:
        raise RuntimeError("réponse vide")
    return content


def _free_ai(history):
    """IA gratuite sans clé (Pollinations) : API compatible OpenAI, puis requête simple en secours."""
    try:
        return _chat_completion(FREE_AI_URL, "", "openai", history, timeout=45)
    except Exception as first:
        convo = "\n".join(
            f"{'Utilisateur' if m['role'] == 'user' else 'EVE'} : {m['content']}"
            for m in history if m["role"] != "system")[-1500:]
        prompt = ("Tu es E.V.E., assistant personnel français, utile et concis. "
                  "Réponds uniquement en français.\n\n" + convo + "\nEVE :")
        try:
            r = requests.get("https://text.pollinations.ai/" + urllib.parse.quote(prompt),
                             timeout=45, headers={"User-Agent": "EVE-Assistant/4.0"})
            text = r.text.strip()
            if not r.ok or not text or text.lower().startswith("<!doctype") or text.startswith("{"):
                raise RuntimeError(f"HTTP {r.status_code}")
            return text
        except Exception as second:
            raise RuntimeError(f"{first} / {second}")


def ask_ai(history, cfg):
    """Retourne (réponse ou None, liste d'erreurs). Ordre : Groq, OpenAI, IA gratuite."""
    errors = []
    if requests is None:
        return None, ["le module requests n'est pas installé"]
    groq_key = (cfg.get("groq_api_key") or os.getenv("GROQ_API_KEY", "")).strip()
    openai_key = (cfg.get("openai_api_key") or os.getenv("OPENAI_API_KEY", "")).strip()
    if groq_key:
        try:
            return _chat_completion(GROQ_URL, groq_key, cfg.get("groq_model") or "llama-3.1-8b-instant",
                                    history), errors
        except Exception as exc:
            errors.append(f"Groq : {exc}")
    if openai_key:
        try:
            return _chat_completion(OPENAI_URL, openai_key, cfg.get("openai_model") or "gpt-4o-mini",
                                    history), errors
        except Exception as exc:
            errors.append(f"OpenAI : {exc}")
    try:
        return _free_ai(history), errors
    except Exception as exc:
        errors.append(f"IA gratuite : {exc}")
    return None, errors


# ============================================================================ Météo
WEATHER_CODES = {
    0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert",
    45: "brouillard", 48: "brouillard givrant",
    51: "bruine légère", 53: "bruine", 55: "bruine forte",
    56: "bruine verglaçante", 57: "bruine verglaçante forte",
    61: "pluie légère", 63: "pluie", 65: "forte pluie",
    66: "pluie verglaçante", 67: "forte pluie verglaçante",
    71: "neige légère", 73: "neige", 75: "forte neige", 77: "grains de neige",
    80: "averses légères", 81: "averses", 82: "fortes averses",
    85: "averses de neige", 86: "fortes averses de neige",
    95: "orage", 96: "orage avec grêle", 99: "violent orage avec grêle",
}


def geocode(city):
    data = http_json("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": city, "count": 1, "language": "fr"})
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"je ne trouve pas la ville « {city} »")
    r = results[0]
    return r["latitude"], r["longitude"], r.get("name", city)


def weather_report(city, tomorrow=False):
    lat, lon, name = geocode(city)
    d = http_json("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })
    daily = d["daily"]
    i = 1 if tomorrow else 0
    rain = daily["precipitation_probability_max"][i] or 0
    tmin, tmax = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
    if tomorrow:
        desc = WEATHER_CODES.get(daily["weather_code"][1], "temps variable")
        return (f"Demain à {name} : {desc}, de {tmin:.0f}° à {tmax:.0f}°, "
                f"risque de pluie {rain:.0f} %.")
    cur = d["current"]
    desc = WEATHER_CODES.get(cur["weather_code"], "temps variable")
    return (f"À {name} : {desc}, {cur['temperature_2m']:.0f}° "
            f"(ressenti {cur['apparent_temperature']:.0f}°), humidité {cur['relative_humidity_2m']:.0f} %, "
            f"vent {cur['wind_speed_10m']:.0f} km/h. Aujourd'hui : de {tmin:.0f}° à {tmax:.0f}°, "
            f"risque de pluie {rain:.0f} %.")


def extract_city(text, default):
    """Trouve la ville après la dernière préposition (« météo à Paris », « survol de l'ISS à Nice »)."""
    n = norm(text)
    n = re.sub(r"\b(demain|aujourd hui|ce soir|ce matin|maintenant)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip(" ?!.")
    m = re.search(r".*\b(?:a|de|pour|sur|dans|en|au|aux)\s+([a-z][a-z' -]*)$", n)
    if not m:
        return default
    preps = {"a", "de", "pour", "sur", "dans", "en", "au", "aux", "le", "la", "les", "l", "du", "des"}
    words = m.group(1).split()
    while words and words[0] in preps:
        words.pop(0)
    city = " ".join(words)
    if not city or len(words) > 4 or re.search(r"moment|apres midi|semaine|week|espace|iss|station", city):
        return default
    return city


# ========================================================================== Satellites
def iss_report():
    d = http_json("https://api.wheretheiss.at/v1/satellites/25544")
    vis = "en pleine lumière" if d.get("visibility") == "daylight" else "dans l'ombre de la Terre"
    return (f"La Station spatiale internationale est à la latitude {d['latitude']:.2f}, "
            f"longitude {d['longitude']:.2f}, altitude {d['altitude']:.0f} km, "
            f"vitesse {d['velocity']:.0f} km/h ({vis}).")


def astronauts_report():
    d = http_json("http://api.open-notify.org/astros.json")
    people = d.get("people") or []
    if not people:
        return f"Il y a actuellement {d.get('number', 0)} personne(s) dans l'espace."
    by_craft = {}
    for p in people:
        by_craft.setdefault(p.get("craft", "?"), []).append(p.get("name", "?"))
    parts = [f"{craft} : {', '.join(names)}" for craft, names in by_craft.items()]
    return f"Il y a {len(people)} personne(s) dans l'espace. " + " | ".join(parts) + "."


def iss_pass_report(city):
    """Pas d'API fiable pour calculer les survols : on ouvre le service officiel de la NASA."""
    _lat, _lon, name = geocode(city)
    webbrowser.open("https://spotthestation.nasa.gov/sightings/")
    return (f"J'ouvre « Spot the Station » de la NASA : choisis {name} (ou ta ville) pour voir "
            "les prochains passages visibles de l'ISS.")


def open_satellite_map(city):
    lat, lon, name = geocode(city)
    webbrowser.open(f"https://www.windy.com/?satellite,{lat:.3f},{lon:.3f},6")
    return f"J'ouvre l'image satellite des nuages au-dessus de {name}."


def satellite_full_report(city):
    parts = []
    for fn in (iss_report, astronauts_report):
        try:
            parts.append(fn())
        except Exception as exc:
            parts.append(f"({fn.__name__} indisponible : {exc})")
    try:
        parts.append(open_satellite_map(city))
    except Exception as exc:
        parts.append(f"Carte : {exc}")
    return " ".join(parts)


# ========================================================================== État du PC
def read_temperatures():
    temps = []
    if psutil and hasattr(psutil, "sensors_temperatures"):
        try:
            for name, entries in (psutil.sensors_temperatures() or {}).items():
                for e in entries:
                    if e.current:
                        temps.append((f"{name} {e.label}".strip(), e.current))
        except Exception:
            pass
    if not temps and requests is not None:  # LibreHardwareMonitor / OpenHardwareMonitor
        try:
            tree = requests.get("http://localhost:8085/data.json", timeout=2).json()

            def walk(node, trail):
                text = node.get("Text", "")
                val = node.get("Value", "")
                if isinstance(val, str) and val.strip().endswith("°C"):
                    try:
                        v = float(val.replace("°C", "").replace(",", ".").strip())
                        temps.append((f"{trail[2]} {text}" if len(trail) > 2 else text, v))
                    except ValueError:
                        pass
                for child in node.get("Children") or []:
                    walk(child, trail + [text])
            walk(tree, [])
        except Exception:
            pass
    try:  # carte NVIDIA : nvidia-smi est installé avec les pilotes
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=_hidden()).stdout
        for line in out.strip().splitlines():
            name, _, val = line.rpartition(",")
            if val.strip().isdigit() and not any(t[0].startswith(name.strip()) for t in temps):
                temps.append((name.strip() or "GPU NVIDIA", float(val)))
    except Exception:
        pass
    if not temps and os.name == "nt":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
                 "| ForEach-Object { $_.CurrentTemperature }"],
                capture_output=True, text=True, timeout=10, creationflags=_hidden()).stdout
            for i, tok in enumerate(out.split(), 1):
                c = float(tok) / 10 - 273.15
                if 0 < c < 120:
                    temps.append((f"Zone thermique {i}", c))
        except Exception:
            pass
    return temps


def pc_report():
    lines = []
    if psutil:
        cpu = psutil.cpu_percent(interval=0.6)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage(os.path.abspath(os.sep)).percent
        lines.append(f"Processeur à {cpu:.0f} % de charge, mémoire {ram:.0f} % utilisée, "
                     f"disque {disk:.0f} % plein.")
        if hasattr(psutil, "sensors_battery"):
            b = psutil.sensors_battery()
            if b:
                lines.append(f"Batterie à {b.percent:.0f} %" + (" (en charge)." if b.power_plugged else "."))
    else:
        lines.append("Le module psutil n'est pas installé : charge du PC indisponible.")
    temps = read_temperatures()
    if temps:
        key = [t for t in temps if re.search(r"cpu|core|package|gpu|ryzen|intel|nvidia|radeon", t[0], re.I)]
        lines.append("Températures : " + ", ".join(f"{n} {v:.0f}°C" for n, v in (key or temps)[:6]) + ".")
    else:
        lines.append(
            "Je ne peux pas lire la température : Windows ne la donne pas sans outil. "
            "Installe LibreHardwareMonitor (gratuit), lance-le, puis dans Options "
            "active « Remote Web Server » > Run.")
    return " ".join(lines)


_HW_SCRIPT = (
    "$o=[ordered]@{"
    "cpu=@(Get-CimInstance Win32_Processor|Select-Object Name,NumberOfCores,NumberOfLogicalProcessors);"
    "gpu=@(Get-CimInstance Win32_VideoController|Select-Object Name);"
    "ram=@(Get-CimInstance Win32_PhysicalMemory|Select-Object Capacity,Speed);"
    "disks=@(Get-CimInstance Win32_DiskDrive|Select-Object Model,Size);"
    "board=@(Get-CimInstance Win32_BaseBoard|Select-Object Manufacturer,Product);"
    "os=@(Get-CimInstance Win32_OperatingSystem|Select-Object Caption)"
    "}; $o|ConvertTo-Json -Depth 4 -Compress"
)


def _as_list(x):
    return x if isinstance(x, list) else ([x] if x else [])


def components_text(data):
    """Met en phrases le JSON renvoyé par PowerShell."""
    lines = []
    for c in _as_list(data.get("cpu")):
        lines.append(f"• Processeur : {str(c.get('Name', '?')).strip()} "
                     f"({c.get('NumberOfCores', '?')} cœurs, {c.get('NumberOfLogicalProcessors', '?')} threads)")
    gpus = [str(g.get("Name", "?")).strip() for g in _as_list(data.get("gpu"))]
    if gpus:
        lines.append("• Carte graphique : " + " + ".join(gpus))
    rams = _as_list(data.get("ram"))
    if rams:
        total = sum(int(r.get("Capacity") or 0) for r in rams) / 1024 ** 3
        speed = max((int(r.get("Speed") or 0) for r in rams), default=0)
        lines.append(f"• Mémoire : {total:.0f} Go en {len(rams)} barrette(s)" + (f", {speed} MHz" if speed else ""))
    for d in _as_list(data.get("disks")):
        size = int(d.get("Size") or 0) / 1000 ** 3
        lines.append(f"• Stockage : {str(d.get('Model', '?')).strip()} (~{size:.0f} Go)")
    for b in _as_list(data.get("board")):
        lines.append(f"• Carte mère : {str(b.get('Manufacturer', '')).strip()} {str(b.get('Product', '')).strip()}".rstrip())
    for o in _as_list(data.get("os")):
        lines.append(f"• Système : {str(o.get('Caption', '?')).strip()}")
    return "Voici les composants de ton PC :\n" + "\n".join(lines)


def components_report():
    if os.name == "nt":
        out = subprocess.run(["powershell", "-NoProfile", "-Command", _HW_SCRIPT],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=30, creationflags=_hidden()).stdout
        return components_text(json.loads(out))
    import platform
    lines = [f"• Processeur : {platform.processor() or platform.machine()}",
             f"• Système : {platform.system()} {platform.release()}"]
    if psutil:
        lines.insert(1, f"• Mémoire : {psutil.virtual_memory().total / 1024 ** 3:.0f} Go")
    return "Voici ce que je peux lire de ce PC :\n" + "\n".join(lines)


# ============================================================================= Lumières
COLORS = {
    "rouge": (255, 0, 0), "vert": (0, 200, 0), "verte": (0, 200, 0),
    "bleu": (0, 60, 255), "bleue": (0, 60, 255), "jaune": (255, 200, 0),
    "orange": (255, 110, 0), "violet": (140, 0, 255), "violette": (140, 0, 255),
    "rose": (255, 60, 160), "cyan": (0, 220, 255),
}


def parse_light_command(n):
    """n = texte normalisé. Retourne (paramètres, phrase de confirmation) ou None."""
    if re.search(r"\b(eteins|eteint|eteindre|coupe|couper|ferme|desactive|desactiver)\b", n):
        return {"on": False}, "J'éteins les lumières."
    for name, kelvin in (("blanc chaud", 2700), ("blanc froid", 6000)):
        if name in n:
            return {"kelvin": kelvin}, f"Lumières en {name}."
    for name, rgb in COLORS.items():
        if re.search(rf"\b{name}\b", n):
            return {"rgb": rgb}, f"Lumières en {name}."
    if re.search(r"\bblanche?\b", n):
        return {"kelvin": 4000}, "Lumières en blanc."
    m = re.search(r"(\d{1,3})\s*(?:%|pour\s*cent|pourcent)", n)
    if m:
        pct = max(1, min(100, int(m.group(1))))
        return {"brightness": pct}, f"Lumières à {pct} %."
    if re.search(r"\b(tamise|tamiser|baisse|baisser)\b", n):
        return {"brightness": 30}, "J'ai tamisé les lumières."
    if re.search(r"\b(allume|allumer|rallume|rallumer|active|activer|mets|met)\b", n):
        return {"on": True}, "J'allume les lumières."
    return None


class Lights:
    """Lumières wifi : WiZ, Yeelight, Philips Hue ou Home Assistant."""

    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def kind(self):
        return str(self.cfg.get("type", "aucune")).strip().lower()

    def configured(self):
        return self.kind in ("wiz", "yeelight", "hue", "homeassistant")

    def apply(self, on=None, brightness=None, rgb=None, kelvin=None):
        args = (on, brightness, rgb, kelvin)
        if self.kind == "wiz":
            self._each_ip(lambda ip: self._wiz(ip, *args))
        elif self.kind == "yeelight":
            self._each_ip(lambda ip: self._yeelight(ip, *args))
        elif self.kind == "hue":
            self._hue(*args)
        elif self.kind == "homeassistant":
            self._homeassistant(*args)
        else:
            raise RuntimeError(f"type de lumière inconnu : {self.kind}")

    def _each_ip(self, fn):
        ips = [ip for ip in self.cfg.get("ips", []) if ip]
        if not ips:
            raise RuntimeError("aucune adresse IP dans eve_config.json (lumieres > ips)")
        errors = []
        for ip in ips:
            try:
                fn(ip)
            except Exception as exc:
                errors.append(f"{ip} : {exc}")
        if len(errors) == len(ips):
            raise RuntimeError("; ".join(errors))

    @staticmethod
    def _wiz(ip, on, brightness, rgb, kelvin):
        params = {}
        if on is not None:
            params["state"] = bool(on)
        if brightness is not None:
            params.update(state=True, dimming=max(10, min(100, brightness)))
        if rgb:
            params.update(state=True, r=rgb[0], g=rgb[1], b=rgb[2])
        if kelvin:
            params.update(state=True, temp=max(2200, min(6500, kelvin)))
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        try:
            s.sendto(json.dumps({"method": "setPilot", "params": params}).encode(), (ip, 38899))
            s.recvfrom(1024)
        except socket.timeout:
            raise RuntimeError("pas de réponse de l'ampoule")
        finally:
            s.close()

    @staticmethod
    def _yeelight(ip, on, brightness, rgb, kelvin):
        cmds = []
        if on is False:
            cmds.append(("set_power", ["off", "smooth", 300]))
        else:
            cmds.append(("set_power", ["on", "smooth", 300]))
            if kelvin:
                cmds.append(("set_ct_abx", [max(1700, min(6500, kelvin)), "smooth", 300]))
            if rgb:
                cmds.append(("set_rgb", [(rgb[0] << 16) + (rgb[1] << 8) + rgb[2], "smooth", 300]))
            if brightness is not None:
                cmds.append(("set_bright", [max(1, min(100, brightness)), "smooth", 300]))
        s = socket.create_connection((ip, 55443), timeout=3)
        try:
            s.settimeout(2)
            for i, (method, params) in enumerate(cmds, 1):
                s.sendall((json.dumps({"id": i, "method": method, "params": params}) + "\r\n").encode())
                try:
                    s.recv(1024)
                except socket.timeout:
                    pass
        finally:
            s.close()

    def _hue(self, on, brightness, rgb, kelvin):
        bridge = str(self.cfg.get("hue_bridge_ip", "")).strip()
        user = str(self.cfg.get("hue_user", "")).strip()
        if not bridge or not user:
            raise RuntimeError("hue_bridge_ip et hue_user manquent dans la config")
        body = {}
        if on is not None:
            body["on"] = bool(on)
        if brightness is not None:
            body.update(on=True, bri=max(1, min(254, round(brightness * 2.54))))
        if rgb:
            h, s, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
            body.update(on=True, hue=int(h * 65535), sat=int(s * 254))
        if kelvin:
            body.update(on=True, ct=max(153, min(500, int(1_000_000 / kelvin))))
        r = requests.put(f"http://{bridge}/api/{user}/groups/0/action", json=body, timeout=5)
        r.raise_for_status()
        errs = [x["error"]["description"] for x in r.json() if isinstance(x, dict) and "error" in x]
        if errs:
            raise RuntimeError("Hue : " + "; ".join(errs))

    def _homeassistant(self, on, brightness, rgb, kelvin):
        base = str(self.cfg.get("ha_url", "")).rstrip("/")
        token = self.cfg.get("ha_token", "")
        entities = self.cfg.get("ha_entities") or []
        if not base or not token or not entities:
            raise RuntimeError("ha_url, ha_token et ha_entities sont requis")
        data = {"entity_id": entities}
        service = "turn_off" if on is False else "turn_on"
        if service == "turn_on":
            if brightness is not None:
                data["brightness_pct"] = brightness
            if rgb:
                data["rgb_color"] = list(rgb)
            if kelvin:
                data["color_temp_kelvin"] = kelvin
        r = requests.post(f"{base}/api/services/light/{service}", json=data, timeout=8,
                          headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()


# =============================================================================== Rappels
def parse_reminder(text):
    """Retourne (échéance, tâche) ou lève ValueError avec un message clair."""
    n = norm(text)
    if len(n) != len(text):
        text = n
    now = datetime.now()
    due, span = None, None

    m = re.search(r"\bdans\s+(?:(\d+)|une?)\s*(demi\s+heure|quart\s+d\s*heure|secondes?|sec|minutes?|min|heures?|h)\b", n)
    if m:
        amount = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2)
        if unit.startswith("demi"):
            delta = timedelta(minutes=30)
        elif unit.startswith("quart"):
            delta = timedelta(minutes=15)
        elif unit.startswith("sec"):
            delta = timedelta(seconds=amount)
        elif unit.startswith("min"):
            delta = timedelta(minutes=amount)
        else:
            delta = timedelta(hours=amount)
        due, span = now + delta, m.span()
    else:
        m = re.search(r"\b(demain\s+)?a\s+(\d{1,2})\s*(?:h|:)\s*(\d{2})?(?!\d)", n)
        if m:
            hour, minute = int(m.group(2)), int(m.group(3) or 0)
            if hour > 23 or minute > 59:
                raise ValueError("Cette heure n'existe pas, essaie par exemple « à 18h30 ».")
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if m.group(1) or due <= now:
                due += timedelta(days=1)
            span = m.span()
    if due is None:
        raise ValueError(
            "Dis-moi quand : par exemple « rappelle-moi dans 10 minutes de sortir le linge » "
            "ou « rappelle-moi à 18h30 d'appeler Paul ».")
    m0 = re.match(r"\s*(?:mets?\s+(?:moi\s+)?un\s+rappel|cree\s+un\s+rappel|rappelle\s+moi|rappeler\s+moi|rappel)\s*", n)
    start = m0.end() if m0 else 0
    before = text[start:span[0]] if span[0] >= start else ""
    task = (before + " " + text[span[1]:]).strip(" ,.;")
    task = re.sub(r"^(?:de\s+|d['’]\s*|que\s+|qu['’]\s*|pour\s+)", "", task, flags=re.I).strip()
    return due, task


# ================================================================================ Applis
_START_APPS = None

BUILTIN_APPS = {
    "calculatrice": ["calc.exe"], "bloc notes": ["notepad.exe"], "notepad": ["notepad.exe"],
    "paint": ["mspaint.exe"], "explorateur": ["explorer.exe"],
    "explorateur de fichiers": ["explorer.exe"], "gestionnaire des taches": ["taskmgr.exe"],
    "parametres": ["explorer.exe", "ms-settings:"], "invite de commandes": ["cmd.exe"],
}
WEBSITES = {
    "google": "https://www.google.com", "youtube": "https://www.youtube.com",
    "chrome": "https://www.google.com/chrome/", "fortnite": "https://www.fortnite.com",
    "roblox": "https://www.roblox.com", "gmail": "https://mail.google.com",
    "netflix": "https://www.netflix.com",
}


def get_start_apps():
    """Applis installées (nom, type, cible) : menu Démarrer (Store inclus), sinon raccourcis .lnk."""
    global _START_APPS
    if _START_APPS is not None:
        return _START_APPS
    apps = []
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=20, creationflags=_hidden()).stdout
            data = json.loads(out) if out.strip() else []
            if isinstance(data, dict):
                data = [data]
            apps = [(d["Name"], "appid", d["AppID"]) for d in data if d.get("Name") and d.get("AppID")]
        except Exception:
            apps = []
        if not apps:
            for base in (os.environ.get("ProgramData"), os.environ.get("APPDATA")):
                if base:
                    root = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                    if root.exists():
                        apps += [(p.stem, "file", str(p)) for p in root.rglob("*.lnk")]
    _START_APPS = apps
    return apps


def find_app(name):
    names = {}
    for a in get_start_apps():
        names.setdefault(norm(a[0]).strip(), a)
    n = norm(name).strip()
    if not n or not names:
        return None
    if n in names:
        return names[n]
    cands = [k for k in names if n in k or k.startswith(n)]
    if cands and len(n) >= 3:
        return names[min(cands, key=len)]
    close = difflib.get_close_matches(n, list(names), n=1, cutoff=0.75)
    return names[close[0]] if close else None


def open_target(target, cfg):
    t = norm(target).strip(" .!?")
    t = re.sub(r"^(?:(?:l\s*)?appli(?:cation)?\s+|le\s+|la\s+|les\s+|l\s+|mon\s+|ma\s+|un\s+|une\s+)+", "", t).strip()
    if not t:
        return None
    for key, path in cfg.get("apps_perso", {}).items():
        if norm(key).strip() == t:
            if os.name == "nt":
                os.startfile(path)
            else:
                subprocess.Popen([path])
            return f"J'ouvre {key}."
    if os.name == "nt" and t in BUILTIN_APPS:
        subprocess.Popen(BUILTIN_APPS[t], shell=False)
        return f"J'ouvre {t}."
    if t in WEBSITES:
        webbrowser.open(WEBSITES[t])
        return f"J'ouvre {t}."
    if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}(?:/\S*)?", t):
        webbrowser.open("https://" + t)
        return f"J'ouvre {t}."
    if os.name != "nt":
        return "L'ouverture d'applis installées n'est disponible que sous Windows."
    app = find_app(t)
    if app:
        name, kind, target_ = app
        if kind == "appid":
            subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + target_])
        else:
            os.startfile(target_)
        return f"J'ouvre {name}."
    return None


# ========================================================================== Contrôle du PC
class PCControl:
    """Prend la souris/le clavier le temps d'UNE tâche, puis rend le contrôle."""

    def __init__(self):
        self.active = False
        self._lock = threading.Lock()

    def available(self):
        return USE_PYAUTOGUI and os.name == "nt"

    def run_task(self, description, actions):
        if not self.available():
            return ("Le contrôle du PC n'est pas disponible (Windows + pyautogui requis).")
        with self._lock:
            self.active = True
            try:
                time.sleep(0.8)
                actions()
                return f"Tâche terminée : {description}. Je te rends le contrôle."
            except Exception as exc:
                if exc.__class__.__name__ == "FailSafeException":
                    return "Arrêt d'urgence détecté : je te rends le contrôle immédiatement."
                return f"J'ai interrompu le contrôle : {exc}"
            finally:
                self.active = False


pc_control = PCControl()

CONTROL_TRIGGER = re.compile(
    r"\b(prends?\s+le\s+controle|prendre\s+le\s+controle|controle\s+(?:le\s+|mon\s+)?pc|"
    r"fais?\s+(?:le\s+)?a\s+ma\s+place|a\s+ma\s+place)\b")


def _type_text(text):
    """Tape un texte : directement en ASCII, sinon via le presse-papiers (accents)."""
    if text.isascii():
        pyautogui.write(text, interval=0.03)
        return
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::InputEncoding=[Text.Encoding]::UTF8; $t=[Console]::In.ReadToEnd(); Set-Clipboard -Value $t"],
            input=text.encode("utf-8"), timeout=8, creationflags=_hidden(), check=False)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        for ch in text:
            try:
                pyautogui.write(ch, interval=0.02)
            except Exception:
                pass


def parse_pc_control(text):
    """Retourne (description, fonction) ou None. Sauf la capture d'écran, il faut une
    formule explicite (« prends le contrôle… », « … à ma place »)."""
    if not USE_PYAUTOGUI:
        return None
    n = norm(text)
    base = text if len(n) == len(text) else n

    if re.search(r"\b(capture d ecran|capture ecran|screenshot)\b", n):
        def do_shot():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder = Path.home() / "Desktop"
            path = (folder if folder.exists() else Path.home()) / f"EVE_capture_{stamp}.png"
            pyautogui.screenshot().save(str(path))
            try:
                os.startfile(str(path))
            except Exception:
                pass
        return "capture d'écran enregistrée sur le Bureau", do_shot

    if not CONTROL_TRIGGER.search(n):
        return None

    m = re.search(r"\b(?:ouvre|lance|demarre)\s+(.+?)(?:\s+et\s+(?:tape|ecris|saisis)\s*:?\s*(.+))?$", n)
    if m:
        target = base[m.start(1):m.end(1)].strip()
        to_type = base[m.start(2):m.end(2)].strip().strip("«»\"'") if m.group(2) else ""

        def do_open():
            open_target(target, load_config())
            if to_type:
                time.sleep(1.5)
                _type_text(to_type)
        shown = re.sub(r"^(?:le|la|les|l['’]|mon|ma)\s*", "", target, flags=re.I)
        return f"ouverture de {shown}" + (" + saisie de texte" if to_type else ""), do_open

    m = re.search(r"\b(?:tape|ecris|saisis)\s*(?:a\s+ma\s+place)?\s*:?\s*(.+)$", n)
    if m:
        content = base[m.start(1):].strip().strip("«»\"'")
        if content:
            def do_type():
                _type_text(content)
            shown = content[:60] + ("…" if len(content) > 60 else "")
            return f"j'ai tapé « {shown} »", do_type

    keys = (
        (r"\b(copie|copier)\b", ("ctrl", "c"), "texte copié (Ctrl+C)"),
        (r"\b(colle|coller)\b", ("ctrl", "v"), "texte collé (Ctrl+V)"),
        (r"\b(selectionne tout|tout selectionner)\b", ("ctrl", "a"), "tout sélectionné (Ctrl+A)"),
        (r"\b(enregistre|sauvegarde)\b", ("ctrl", "s"), "enregistrement demandé (Ctrl+S)"),
        (r"\b(ferme|fermer)\b.*\b(fenetre|application|appli)\b", ("alt", "f4"), "fenêtre active fermée (Alt+F4)"),
    )
    for pattern, combo, desc in keys:
        if re.search(pattern, n):
            def do_keys(combo=combo):
                pyautogui.hotkey(*combo)
            return desc, do_keys
    return None


# ===================================================================== Cerveau (fenêtre + web)
class Reply:
    """Résultat d'une commande : soit un texte immédiat, soit une tâche lente à exécuter."""

    def __init__(self, text=None, fn=None, args=(), status="…", remember=True, speak=True):
        self.text, self.fn, self.args = text, fn, args
        self.status, self.remember, self.speak = status, remember, speak


def wake_split(text):
    """(mot d'éveil trouvé ?, reste de la phrase)."""
    n = norm(text)
    m = WAKE_SEARCH.search(n)
    if not m:
        return False, text
    base = text if len(n) == len(text) else n
    return True, base[m.end():].strip(" ,.!?:;-")


def ai_failure_text(errors):
    return ("Je n'arrive pas à joindre une IA pour le moment (Internet ?). "
            "Mes commandes (lumières, météo, satellites, rappels, applis, contrôle PC) "
            "marchent quand même.\n\n"
            "Astuce : une clé gratuite sur https://console.groq.com, collée dans Config "
            "(groq_api_key), rend les réponses beaucoup plus fiables.\n\n"
            "Détails : " + " | ".join(errors[:3]))


class Brain:
    """Comprend les commandes. Utilisé par la fenêtre ET par la version web."""

    def __init__(self):
        self.lock = threading.Lock()
        self.brain = Brain()
        self.web = None

    # -- rappels
    def _load_reminders(self):
        try:
            if REMINDERS_PATH.exists():
                data = json.loads(REMINDERS_PATH.read_text(encoding="utf-8"))
                return [r for r in data if "due" in r and "text" in r]
        except Exception:
            pass
        return []

    def _save_reminders(self):
        try:
            REMINDERS_PATH.write_text(json.dumps(self.reminders, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        except Exception:
            pass

    def pop_due(self):
        """Retourne (et retire) les rappels arrivés à échéance, sous forme de phrases."""
        now = datetime.now()
        with self.lock:
            due_now = [r for r in self.reminders if datetime.fromisoformat(r["due"]) <= now]
            if due_now:
                self.reminders = [r for r in self.reminders if r not in due_now]
                self._save_reminders()
        out = []
        for r in due_now:
            late = (now - datetime.fromisoformat(r["due"])).total_seconds() > 90
            out.append(f"{'⏰ Rappel manqué' if late else '⏰ Rappel'} : "
                       f"{r['text'] or 'tu m’avais demandé un rappel.'}")
        return out

    def _list_reminders(self):
        if not self.reminders:
            return Reply("Tu n'as aucun rappel en attente.", remember=False)
        lines = [f"• {datetime.fromisoformat(r['due']).strftime('%d/%m %H:%M')} — {r['text'] or '(sans texte)'}"
                 for r in sorted(self.reminders, key=lambda r: r["due"])]
        return Reply("Tes rappels :\n" + "\n".join(lines), remember=False, speak=False)

    # ------------------------------------------------------------------- commandes
    def dispatch(self, text):
        """Passe la phrase au cerveau. Retourne True si c'était une commande."""
        r = self.brain.handle(text)
        if r is None:
            return False
        if r.fn:
            self.run_async(r.fn, *r.args, status=r.status)
        else:
            self.say(r.text, remember=r.remember, speak=r.speak)
        return True

    def _check_reminders(self):
        msgs = self.brain.pop_due()
        if msgs:
            for msg in msgs:
                self.say(msg, remember=False)
            try:
                self.root.bell()
                self.root.deiconify()
                self.root.lift()
            except Exception:
                pass
        self.root.after(1000, self._check_reminders)

    def start_web(self):
        """Lance la version web locale et l'ouvre dans le navigateur."""
        try:
            if self.web is None:
                self.web = WebServer(self.brain)
            self.web.start()
        except OSError as exc:
            port = self.web.port if self.web else "?"
            self.web = None
            self.say(f"Je n'arrive pas à démarrer la version web (le port {port} est peut-être déjà "
                     f"utilisé, change « web_port » dans Config) : {exc}", remember=False, speak=False)
            return
        url = self.web.url()
        webbrowser.open(url)
        extra = ""
        if self.web.lan and self.web.lan_ip():
            extra = (f"\nDepuis ton téléphone (même wifi) : {self.web.url(self.web.lan_ip())}\n"
                     "Le contrôle du PC reste réservé à ce PC.")
        self.say(f"La version web est ouverte : {url}{extra}", remember=False, speak=False)

    # ------------------------------------------------------------------------ IA
    def _get_ai_reply(self, history):
        reply, errors = ask_ai(history, load_config())
        remember = True
        if not reply:
            remember = False
            reply = ("Je n'arrive pas à joindre une IA pour le moment (Internet ?). "
                     "Mes commandes (lumières, météo, satellites, rappels, applis, contrôle PC) "
                     "marchent quand même.\n\n"
                     "Astuce : une clé gratuite sur https://console.groq.com, collée dans Config "
                     "(groq_api_key), rend les réponses beaucoup plus fiables.\n\n"
                     "Détails : " + " | ".join(errors[:3]))
        self.ui_queue.put(("ai_done", reply, remember))

    # ------------------------------------------------------------------- divers
    def attach_file(self):
        path = filedialog.askopenfilename(
            title="Choisir un fichier texte ou code",
            filetypes=[("Fichiers texte/code", "*.txt *.py *.json *.md *.html *.css *.js *.log *.csv"),
                       ("Tous les fichiers", "*.*")])
        if not path:
            return
        try:
            p = Path(path)
            if p.stat().st_size > 1_000_000:
                messagebox.showwarning("Fichier volumineux", "Choisis un fichier de moins de 1 Mo.")
                return
            content = p.read_text(encoding="utf-8", errors="replace")
            self.input_var.set(f"Analyse ce fichier : {p.name}\n\n{content[:8000]}")
            self.entry.focus_set()
        except Exception as exc:
            messagebox.showerror("Lecture impossible", str(exc))

    def open_config(self):
        load_config()  # crée le fichier s'il n'existe pas
        try:
            if os.name == "nt":
                subprocess.Popen(["notepad.exe", str(CONFIG_PATH)])
            else:
                subprocess.Popen(["xdg-open", str(CONFIG_PATH)])
            self.say("J'ouvre le fichier de configuration : ville, lumières, applis perso, "
                     "et clé Groq gratuite pour de meilleures réponses. Enregistre puis reviens ici, "
                     "c'est pris en compte tout de suite.", remember=False)
        except Exception as exc:
            messagebox.showinfo("Config", f"Fichier : {CONFIG_PATH}\n\n{exc}")

    def show_diagnostic(self):
        cfg = load_config()
        lines = [
            f"Python : {sys.version.split()[0]}",
            f"customtkinter : {'installé' if USE_CTK else 'ABSENT (Tkinter de secours)'}",
            f"requests : {'installé' if requests else 'ABSENT'}",
            f"pyttsx3 (voix) : {'installé' if pyttsx3 else 'ABSENT'}",
            f"SpeechRecognition (micro) : {'installé' if sr else 'ABSENT'}",
            f"psutil (état PC) : {'installé' if psutil else 'ABSENT'}",
            f"pyautogui (contrôle PC) : {'installé' if USE_PYAUTOGUI else 'ABSENT'}",
            f"Ville météo : {cfg['ville']}",
            f"Lumières : {cfg['lumieres'].get('type', 'aucune')} {cfg['lumieres'].get('ips', '')}",
            f"Rappels en attente : {len(self.brain.reminders)}",
            f"Clé Groq : {'oui' if (cfg.get('groq_api_key') or os.getenv('GROQ_API_KEY')) else 'non (IA gratuite utilisée)'}",
            f"Clé OpenAI : {'oui' if (cfg.get('openai_api_key') or os.getenv('OPENAI_API_KEY')) else 'non'}",
            f"Fichier de config : {CONFIG_PATH}",
        ]
        if requests is not None:
            try:
                r = requests.post(FREE_AI_URL, timeout=10, json={
                    "model": "openai", "messages": [{"role": "user", "content": "Dis juste : ok"}]})
                lines.append(f"IA gratuite : {'OK' if r.ok else 'HTTP ' + str(r.status_code)}")
            except Exception as exc:
                lines.append(f"IA gratuite : injoignable ({exc})")
        messagebox.showinfo("Diagnostic EVE", "\n".join(lines))

    def clear_chat(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._append_chat("EVE", "Discussion effacée. Je suis prête !")

    def run(self):
        self.root.mainloop()


def main():
    try:
        EveApp().run()
    except Exception:
        err = traceback.format_exc()
        try:
            LOG_PATH.write_text(err, encoding="utf-8")
        except Exception:
            pass
        try:
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("E.V.E. — erreur au démarrage", err[-1200:] + f"\n\nDétails : {LOG_PATH}")
        except Exception:
            pass


def main_web():
    """python eve_ia.py --web : uniquement la version web, sans fenêtre."""
    web = WebServer(Brain())
    try:
        web.start()
    except OSError as exc:
        print(f"Impossible de démarrer la version web : {exc}")
        return
    print(f"E.V.E. version web : {web.url()}")
    webbrowser.open(web.url())
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main_web() if "--web" in sys.argv else main()
