# E.V.E. — Assistant personnel Windows (v3)
#
# Fonctions : discussion (IA en ligne gratuite, sans Ollama obligatoire),
# voix, météo, données satellites légales (ISS, astronautes, survols),
# température/état du PC, rappels, ouverture d'applis, lumières wifi,
# contrôle du PC à la demande (souris/clavier) qui s'arrête dès la fin
# de la tâche, mot d'éveil « hey EVE » / « ok EVE ».
#
# Installation : double-clique sur lancer_eve.bat   (ou : python eve_ia.py)
# Réglages (ville, lumières, applis, clés API) : eve_config.json (bouton « Config »).
#
# IA : fonctionne sans rien installer (API publique gratuite).
# Optionnel : clé Groq gratuite, OpenAI, ou Ollama local pour de meilleures réponses.

import os
import sys
import json
import re
import time
import queue
import socket
import difflib
import threading
import subprocess
import unicodedata
import urllib.parse
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox

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


APP_NAME = "E.V.E. | Assistant personnel"
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "eve_config.json"
REMINDERS_PATH = BASE_DIR / "eve_rappels.json"

OLLAMA_URL = os.getenv("EVE_OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("EVE_OLLAMA_MODEL", "llama3.2:3b")
ONLINE_API_KEY = os.getenv("OPENAI_API_KEY", "")
ONLINE_MODEL = os.getenv("EVE_ONLINE_MODEL", "gpt-4o-mini")
ONLINE_URL = os.getenv("EVE_ONLINE_URL", "https://api.openai.com/v1/chat/completions")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("EVE_GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "Tu es E.V.E., un assistant personnel utile, prudent et chaleureux. "
    "Tu réponds en français, de façon claire et concise. "
    "Tu n'affirmes pas avoir effectué une action si tu ne l'as pas réellement faite. "
    "L'application qui t'héberge sait déjà gérer, via des commandes détectées avant toi : "
    "lumières wifi, météo, satellites, température du PC, rappels, ouverture d'applis "
    "et contrôle ponctuel du PC (souris/clavier). "
    "Quand l'utilisateur te demande de prendre le contrôle du PC, confirme clairement "
    "que tu le fais puis que tu le libères dès la fin de la tâche."
)

WAKE_SEARCH = re.compile(r"\b(?:hey|hei|he|ok|okay|okey)\s*,?\s*(?:eve|yves|eva|ive)\b")
WAKE_REPLY = (
    "Oui, je suis là ! Je peux allumer les lumières, donner la météo et les données "
    "satellites, surveiller le PC, ouvrir tes applis, te faire des rappels, et même "
    "prendre le contrôle de ton PC le temps d'une tâche précise."
)

HELP_TEXT = (
    "Voici ce que je sais faire :\n"
    "• « allume / éteins les lumières », « lumières à 50 % », « lumières en rouge »\n"
    "• « météo », « météo à Paris », « météo demain »\n"
    "• « où est l'ISS », « astronautes dans l'espace », « image satellite », « prochain survol ISS »\n"
    "• « température du PC » ou « état du PC »\n"
    "• « rappelle-moi dans 10 minutes de sortir le linge », « mes rappels »\n"
    "• « ouvre Spotify », « lance Word », « ouvre YouTube »\n"
    "• « recherche sur internet … »\n"
    "• Contrôle PC (ponctuel, s'arrête dès la fin) :\n"
    "    « prends le contrôle et ouvre le bloc-notes »,\n"
    "    « tape à ma place : bonjour tout le monde »,\n"
    "    « fais une capture d'écran », « copie le texte sélectionné »\n"
    "• Dis « hey EVE » ou « ok EVE » (écoute permanente activée).\n\n"
    "IA : marche sans Ollama (API gratuite intégrée). "
    "Pour de meilleures réponses : clé Groq gratuite (console.groq.com) "
    "ou Ollama local optionnel."
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
    "openai_api_key": "",
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg["ville"] = data.get("ville", cfg["ville"])
            cfg["lumieres"].update(data.get("lumieres", {}))
            cfg["apps_perso"].update(data.get("apps_perso", {}))
            cfg["groq_api_key"] = data.get("groq_api_key", cfg.get("groq_api_key", ""))
            cfg["openai_api_key"] = data.get("openai_api_key", cfg.get("openai_api_key", ""))
        else:
            CONFIG_PATH.write_text(
                json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def norm(text):
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[-’'`]", " ", t)


def _hidden():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


def http_json(url, **kwargs):
    if requests is None:
        raise RuntimeError("le module requests n'est pas installé")
    r = requests.get(url, timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()


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
    n = norm(text)
    n = re.sub(r"\b(demain|aujourd hui|ce soir|ce matin|maintenant)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip(" ?!.")
    m = re.search(r"\b(?:a|de|pour|sur|dans|en|au|aux)\s+([a-z][a-z' -]*)$", n)
    if not m:
        return default
    preps = {"a", "de", "pour", "sur", "dans", "en", "au", "aux", "le", "la", "les", "l"}
    words = m.group(1).split()
    while words and words[0] in preps:
        words.pop(0)
    return " ".join(words) if words else default


# ------------------------------------------------------------------ satellite (APIs publiques légales)
def iss_report():
    d = http_json("https://api.wheretheiss.at/v1/satellites/25544")
    vis = "visible" if d.get("visibility") == "daylight" else "dans l'ombre de la Terre"
    return (f"La Station spatiale internationale est à la latitude {d['latitude']:.2f}, "
            f"longitude {d['longitude']:.2f}, altitude {d['altitude']:.0f} km, "
            f"vitesse {d['velocity']:.0f} km/h ({vis}).")


def astronauts_report():
    d = http_json("http://api.open-notify.org/astros.json")
    people = d.get("people") or []
    n = d.get("number", len(people))
    if not people:
        return f"Il y a actuellement {n} personne(s) dans l'espace."
    by_craft = {}
    for p in people:
        by_craft.setdefault(p.get("craft", "?"), []).append(p.get("name", "?"))
    parts = [f"{craft} : {', '.join(names)}" for craft, names in by_craft.items()]
    return f"Il y a {n} personne(s) dans l'espace. " + " | ".join(parts) + "."


def iss_pass_report(city):
    lat, lon, name = geocode(city)
    try:
        d = http_json("http://api.open-notify.org/iss-pass.json",
                      params={"lat": lat, "lon": lon, "n": 3})
        passes = d.get("response") or []
        if not passes:
            return f"Aucun survol proche trouvé au-dessus de {name}."
        lines = []
        for p in passes:
            when = datetime.fromtimestamp(p["risetime"])
            dur = p.get("duration", 0)
            lines.append(f"• {when.strftime('%d/%m à %H:%M')} (environ {dur // 60} min {dur % 60} s)")
        return f"Prochains survols de l'ISS au-dessus de {name} :\n" + "\n".join(lines)
    except Exception:
        webbrowser.open(
            f"https://spotthestation.nasa.gov/sightings/view.cfm?"
            f"country=France&region=None&city={urllib.parse.quote(name)}")
        return (f"J'ouvre les prévisions de survol NASA pour {name}. "
                "L'API de prédiction est temporairement indisponible.")


def open_satellite_map(city):
    lat, lon, name = geocode(city)
    webbrowser.open(f"https://www.windy.com/?satellite,{lat:.3f},{lon:.3f},6")
    return f"J'ouvre l'image satellite des nuages au-dessus de {name}."


def satellite_full_report(city):
    parts = []
    try:
        parts.append(iss_report())
    except Exception as e:
        parts.append(f"ISS : indisponible ({e})")
    try:
        parts.append(astronauts_report())
    except Exception as e:
        parts.append(f"Astronautes : indisponible ({e})")
    try:
        parts.append(open_satellite_map(city))
    except Exception as e:
        parts.append(f"Carte : {e}")
    return " ".join(parts)


# ------------------------------------------------------------------- PC / temp
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
    if not temps and requests is not None:
        try:
            tree = requests.get("http://localhost:8085/data.json", timeout=2).json()

            def walk(node, trail):
                text = node.get("Text", "")
                val = node.get("Value", "")
                if isinstance(val, str) and val.strip().endswith("°C"):
                    try:
                        v = float(val.replace("°C", "").replace(",", ".").strip())
                        label = f"{trail[2]} {text}" if len(trail) > 2 else text
                        temps.append((label, v))
                    except ValueError:
                        pass
                for child in node.get("Children") or []:
                    walk(child, trail + [text])
            walk(tree, [])
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
        shown = (key or temps)[:6]
        lines.append("Températures : " + ", ".join(f"{n} {v:.0f}°C" for n, v in shown) + ".")
    else:
        lines.append(
            "Je ne peux pas lire la température : Windows ne la donne pas sans outil. "
            "Installe LibreHardwareMonitor (gratuit), lance-le, puis dans Options "
            "active « Remote Web Server » > Run.")
    return " ".join(lines)


# --------------------------------------------------------------------- lumières
COLORS = {
    "rouge": (255, 0, 0), "vert": (0, 200, 0), "verte": (0, 200, 0),
    "bleu": (0, 60, 255), "bleue": (0, 60, 255), "jaune": (255, 200, 0),
    "orange": (255, 110, 0), "violet": (140, 0, 255), "violette": (140, 0, 255),
    "rose": (255, 60, 160), "cyan": (0, 220, 255),
}


def parse_light_command(n):
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
    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def kind(self):
        return str(self.cfg.get("type", "aucune")).strip().lower()

    def configured(self):
        return self.kind in ("wiz", "yeelight", "hue", "homeassistant")

    def apply(self, on=None, brightness=None, rgb=None, kelvin=None):
        k = self.kind
        args = (on, brightness, rgb, kelvin)
        if k == "wiz":
            self._each_ip(lambda ip: self._wiz(ip, *args))
        elif k == "yeelight":
            self._each_ip(lambda ip: self._yeelight(ip, *args))
        elif k == "hue":
            self._hue(*args)
        elif k == "homeassistant":
            self._homeassistant(*args)
        else:
            raise RuntimeError(f"type de lumière inconnu : {k}")

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
        msg = json.dumps({"method": "setPilot", "params": params}).encode()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        try:
            s.sendto(msg, (ip, 38899))
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
                s.recv(1024)
        finally:
            s.close()

    def _hue(self, on, brightness, rgb, kelvin):
        bridge = self.cfg.get("hue_bridge_ip", "").strip()
        user = self.cfg.get("hue_user", "").strip()
        if not bridge or not user:
            raise RuntimeError("hue_bridge_ip et hue_user manquent dans la config")
        body = {}
        if on is not None:
            body["on"] = bool(on)
        if brightness is not None:
            body["bri"] = max(1, min(254, int(brightness * 2.54)))
        if rgb:
            r, g, b = [c / 255 for c in rgb]
            X = r * 0.664511 + g * 0.154324 + b * 0.162028
            Y = r * 0.283881 + g * 0.668433 + b * 0.047685
            Z = r * 0.000088 + g * 0.072310 + b * 0.986039
            s = X + Y + Z
            body["xy"] = [X / s, Y / s] if s else [0.3, 0.3]
        if kelvin:
            body["ct"] = max(153, min(500, int(1_000_000 / kelvin)))
        url = f"http://{bridge}/api/{user}/groups/0/action"
        r = requests.put(url, json=body, timeout=5)
        r.raise_for_status()

    def _homeassistant(self, on, brightness, rgb, kelvin):
        base = self.cfg.get("ha_url", "").rstrip("/")
        token = self.cfg.get("ha_token", "")
        entities = self.cfg.get("ha_entities") or []
        if not base or not token or not entities:
            raise RuntimeError("ha_url, ha_token et ha_entities sont requis")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        service = "turn_on" if on is not False else "turn_off"
        data = {"entity_id": entities}
        if service == "turn_on":
            if brightness is not None:
                data["brightness_pct"] = brightness
            if rgb:
                data["rgb_color"] = list(rgb)
            if kelvin:
                data["color_temp_kelvin"] = kelvin
        r = requests.post(f"{base}/api/services/light/{service}", headers=headers, json=data, timeout=8)
        r.raise_for_status()


# ----------------------------------------------------------------------- rappels
def parse_reminder(text):
    n = norm(text)
    now = datetime.now()
    due, span = None, (0, 0)

    m = re.search(r"\bdans\s+(\d+)\s*(secondes?|secs?|minutes?|mins?|heures?|hrs?|h)\b", n)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("sec"):
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
            if m.group(1):
                due += timedelta(days=1)
            elif due <= now:
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
    task = re.sub(r"^(?:de|d |a |pour )\s*", "", task, flags=re.I).strip()
    return due, task


# --------------------------------------------------------------------- applis
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
    apps = []
    if os.name != "nt":
        return apps
    try:
        start = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs"
        user = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs"
        for root in (start, user):
            if not root.exists():
                continue
            for p in root.rglob("*.lnk"):
                apps.append((p.stem, "path", str(p)))
    except Exception:
        pass
    return apps


_START_CACHE = None


def find_app(name):
    global _START_CACHE
    if _START_CACHE is None:
        _START_CACHE = get_start_apps()
    n = norm(name)
    best, score = None, 0.0
    for stem, kind, target in _START_CACHE:
        s = difflib.SequenceMatcher(None, n, norm(stem)).ratio()
        if s > score:
            score, best = s, (stem, kind, target)
    return best if score >= 0.55 else None


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


# ============================================================== Contrôle PC
class PCControl:
    def __init__(self):
        self.active = False
        self._lock = threading.Lock()

    def available(self):
        return USE_PYAUTOGUI and os.name == "nt"

    def run_task(self, description, actions):
        if not self.available():
            return ("Le contrôle du PC n'est pas disponible. "
                    "Installe pyautogui (le .bat le fait) et utilise Windows.")
        with self._lock:
            self.active = True
            try:
                time.sleep(0.4)
                actions()
                return f"Tâche terminée : {description}. Je te rends le contrôle."
            except Exception as exc:
                return f"J'ai interrompu le contrôle : {exc}"
            finally:
                self.active = False


pc_control = PCControl()


def _paste_text(text):
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Set-Clipboard -Value @'\n{text}\n'@"],
            timeout=5, creationflags=_hidden(), check=False)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        for ch in text:
            try:
                pyautogui.write(ch, interval=0.02)
            except Exception:
                pass


def parse_pc_control(text):
    if not USE_PYAUTOGUI:
        return None
    n = norm(text)
    original = text

    if re.search(r"\b(capture d ecran|screenshot|capture ecran|prends? (une )?capture)\b", n):
        def do():
            path = Path.home() / "Desktop" / f"EVE_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            if not path.parent.exists():
                path = Path.home() / f"EVE_capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            img = pyautogui.screenshot()
            img.save(str(path))
            try:
                os.startfile(str(path))
            except Exception:
                pass
        return "capture d'écran enregistrée sur le Bureau", do

    m = re.search(
        r"(?:tape|ecris|ecrire|saisis|saisir)\s+(?:a\s+ma\s+place\s+)?:?\s*[«\"]?(.+?)[»\"]?\s*$",
        original, re.I | re.S)
    if not m:
        m = re.search(
            r"(?:prends?\s+le\s+controle|controle\s+(?:le\s+)?pc|fais?\s+a\s+ma\s+place).*"
            r"(?:et\s+)?(?:tape|ecris)\s*:?\s*[«\"]?(.+?)[»\"]?\s*$",
            original, re.I | re.S)
    if m:
        content = m.group(1).strip().strip("«»\"'")
        if content:
            def do():
                time.sleep(0.5)
                if content.isascii():
                    pyautogui.write(content, interval=0.03)
                else:
                    _paste_text(content)
            return f"j'ai tapé « {content[:60]}{'…' if len(content) > 60 else ''} »", do

    if re.search(r"\b(copie|copier)\b.*\b(selection|texte)\b|\bcopie le texte\b", n):
        def do():
            pyautogui.hotkey("ctrl", "c")
        return "texte copié (Ctrl+C)", do

    if re.search(r"\b(colle|coller)\b", n) and re.search(r"\b(texte|ici|la)\b", n):
        def do():
            pyautogui.hotkey("ctrl", "v")
        return "texte collé (Ctrl+V)", do

    if re.search(r"\b(selectionne tout|tout selectionner)\b", n):
        def do():
            pyautogui.hotkey("ctrl", "a")
        return "tout sélectionné (Ctrl+A)", do

    if re.search(r"\b(enregistre|sauvegarde)\b", n) and not re.search(r"rappel", n):
        def do():
            pyautogui.hotkey("ctrl", "s")
        return "enregistrement demandé (Ctrl+S)", do

    m = re.search(
        r"(?:prends?\s+le\s+controle|controle\s+(?:le\s+)?pc|fais?\s+a\s+ma\s+place).*"
        r"(?:et\s+)?(?:ouvre|lance|demarre)\s+(.+?)(?:\s+et\s+(?:tape|ecris)\s*:?\s*(.+))?$",
        original, re.I | re.S)
    if m:
        target = m.group(1).strip()
        to_type = (m.group(2) or "").strip().strip("«»\"'") if m.lastindex >= 2 else ""

        def do():
            open_target(target, load_config())
            time.sleep(1.2)
            if to_type:
                if to_type.isascii():
                    pyautogui.write(to_type, interval=0.03)
                else:
                    _paste_text(to_type)
        desc = f"ouverture de {target}"
        if to_type:
            desc += " + saisie de texte"
        return desc, do

    m = re.search(
        r"(?:prends?\s+le\s+controle|controle\s+(?:le\s+)?pc|fais?\s+a\s+ma\s+place)\s+"
        r"(?:et\s+)?(?:ouvre|lance|demarre)\s+(.+)$",
        original, re.I)
    if m:
        target = m.group(1).strip()

        def do():
            open_target(target, load_config())
        return f"ouverture de {target}", do

    if re.search(r"\b(ferme|fermer)\b.*\b(fenetre|application|appli)\b", n):
        def do():
            pyautogui.hotkey("alt", "f4")
        return "fermeture de la fenêtre active (Alt+F4)", do

    return None


# ------------------------------------------------------------------- application
class EveApp:
    def __init__(self):
        if USE_CTK:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
            self.root.configure(bg="#101827")

        self.root.title(APP_NAME)
        self.root.geometry("980x700")
        self.root.minsize(700, 520)
        self.cfg = load_config()
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.ui_queue = queue.Queue()
        self.tts_engine = None
        self.tts_voice_id = None
        self.tts_lock = threading.Lock()
        self.speaking = False
        self.listening = False
        self.busy = False
        self.always_stop = None
        self.awake_until = 0.0
        self.reminders = self._load_reminders()
        self._build_ui()
        self._init_tts()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._process_ui_queue)
        self.root.after(1000, self._check_reminders)
        self._set_status("Prête — dis « hey EVE » après avoir activé l'écoute permanente")

    def _widget(self, kind, master, **kwargs):
        if USE_CTK:
            mapping = {"frame": ctk.CTkFrame, "label": ctk.CTkLabel, "button": ctk.CTkButton,
                       "entry": ctk.CTkEntry, "textbox": ctk.CTkTextbox}
            return mapping[kind](master, **kwargs)
        mapping = {"frame": tk.Frame, "label": tk.Label, "button": tk.Button,
                   "entry": tk.Entry, "textbox": tk.Text}
        kwargs.pop("corner_radius", None)
        if kind == "frame":
            kwargs.setdefault("bg", "#172235")
        elif kind == "label":
            kwargs.setdefault("bg", "#172235")
            kwargs.setdefault("fg", "#edf4ff")
        elif kind == "button":
            kwargs.pop("width", None)
            kwargs.setdefault("bg", "#2456a6")
            kwargs.setdefault("fg", "white")
            kwargs.setdefault("activebackground", "#326bc4")
            kwargs.setdefault("padx", 10)
        elif kind == "entry":
            kwargs.setdefault("bg", "#202d42")
            kwargs.setdefault("fg", "white")
            kwargs.setdefault("insertbackground", "white")
        elif kind == "textbox":
            kwargs.setdefault("bg", "#0d1520")
            kwargs.setdefault("fg", "#edf4ff")
            kwargs.setdefault("insertbackground", "white")
        return mapping[kind](master, **kwargs)

    def _build_ui(self):
        top = self._widget("frame", self.root, corner_radius=0)
        top.pack(fill="x", padx=10, pady=(10, 4))

        title = self._widget("label", top, text="E.V.E.  ·  Assistant personnel",
                             font=("Segoe UI", 18, "bold") if not USE_CTK else ("Segoe UI", 18))
        title.pack(side="left", padx=8, pady=6)

        self.status_var = tk.StringVar(value="Prête")
        status = self._widget("label", top, textvariable=self.status_var,
                              font=("Segoe UI", 11) if not USE_CTK else ("Segoe UI", 12))
        status.pack(side="right", padx=8)

        chat_frame = self._widget("frame", self.root, corner_radius=8)
        chat_frame.pack(fill="both", expand=True, padx=10, pady=4)
        self.chat = self._widget("textbox", chat_frame, wrap="word",
                                 font=("Segoe UI", 12) if not USE_CTK else ("Segoe UI", 13))
        self.chat.pack(fill="both", expand=True, padx=6, pady=6)
        self.chat.configure(state="disabled")

        bottom = self._widget("frame", self.root, corner_radius=0)
        bottom.pack(fill="x", padx=10, pady=(4, 10))

        self.input_var = tk.StringVar()
        self.entry = self._widget("entry", bottom, textvariable=self.input_var,
                                  font=("Segoe UI", 13) if not USE_CTK else ("Segoe UI", 14))
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=6)
        self.entry.bind("<Return>", lambda e: self.send_message())

        self.send_btn = self._widget("button", bottom, text="Envoyer", command=self.send_message, width=90)
        self.send_btn.pack(side="left", padx=2)

        self.mic_btn = self._widget("button", bottom, text="🎤", command=self.toggle_listen, width=44)
        self.mic_btn.pack(side="left", padx=2)

        self.always_btn = self._widget("button", bottom, text="Écoute permanente",
                                       command=self.toggle_always_listen, width=140)
        self.always_btn.pack(side="left", padx=2)

        tools = self._widget("frame", self.root, corner_radius=0)
        tools.pack(fill="x", padx=10, pady=(0, 8))
        for label, cmd in (
            ("Aide", lambda: self.say(HELP_TEXT, remember=False)),
            ("Config", self.open_config),
            ("Diagnostic", self.show_diagnostic),
            ("Effacer", self.clear_chat),
        ):
            b = self._widget("button", tools, text=label, command=cmd, width=100)
            b.pack(side="left", padx=3)

        self._append_chat("EVE", "Bonjour ! Je suis E.V.E. Je fonctionne sans Ollama "
                          "(IA en ligne gratuite). Dis-moi ce dont tu as besoin, "
                          "ou tape « aide ».")

    def _append_chat(self, who, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", f"{who} : " + text.strip() + "\n\n")
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _set_status(self, msg):
        self.status_var.set(msg)

    def _process_ui_queue(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "status":
                    self._set_status(item[1])
                elif kind == "say":
                    self.say(item[1], remember=item[2] if len(item) > 2 else True)
                elif kind == "heard":
                    self.process_user_text(item[1])
                elif kind == "always_ready":
                    self.always_stop = item[1]
                    self._set_status("Écoute permanente active — dis « hey EVE »")
                    self.always_btn.configure(text="Arrêter l'écoute")
                elif kind == "always_error":
                    messagebox.showerror("Écoute permanente", item[1])
                    self.always_btn.configure(text="Écoute permanente")
                elif kind == "ai_done":
                    self.busy = False
                    self.send_btn.configure(state="normal")
                    self.entry.configure(state="normal")
                    self.say(item[1], remember=item[2] if len(item) > 2 else True)
                    self._set_status("Prête")
                elif kind == "control_start":
                    self._set_status("🎛 Contrôle PC en cours…")
                elif kind == "control_end":
                    self._set_status("Prête — contrôle libéré")
        except queue.Empty:
            pass
        self.root.after(100, self._process_ui_queue)

    def _init_tts(self):
        if pyttsx3 is None:
            return
        try:
            self.tts_engine = pyttsx3.init()
            voices = self.tts_engine.getProperty("voices") or []
            for v in voices:
                name = (v.name or "").lower()
                if "fr" in name or "french" in name or "hortense" in name or "julie" in name:
                    self.tts_voice_id = v.id
                    break
            if self.tts_voice_id:
                self.tts_engine.setProperty("voice", self.tts_voice_id)
            self.tts_engine.setProperty("rate", 175)
        except Exception:
            self.tts_engine = None

    def say(self, text, remember=True):
        self._append_chat("EVE", text)
        if remember:
            self.messages.append({"role": "assistant", "content": text})
        if self.tts_engine is None:
            return
        threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _speak(self, text):
        with self.tts_lock:
            self.speaking = True
            try:
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
            except Exception:
                pass
            finally:
                self.speaking = False

    def toggle_listen(self):
        if self.listening or self.busy:
            return
        if sr is None:
            messagebox.showinfo("Micro", "SpeechRecognition n'est pas installé.")
            return
        self.listening = True
        self._set_status("J'écoute…")
        threading.Thread(target=self._listen_once, daemon=True).start()

    def _listen_once(self):
        try:
            rec = sr.Recognizer()
            with sr.Microphone() as source:
                rec.adjust_for_ambient_noise(source, duration=0.6)
                audio = rec.listen(source, timeout=6, phrase_time_limit=12)
            text = rec.recognize_google(audio, language="fr-FR")
            self.ui_queue.put(("heard", text))
        except sr.WaitTimeoutError:
            self.ui_queue.put(("status", "Je n'ai rien entendu."))
        except Exception as exc:
            self.ui_queue.put(("status", f"Micro : {exc}"))
        finally:
            self.listening = False

    def toggle_always_listen(self):
        if self.always_stop is not None:
            try:
                self.always_stop(wait_for_stop=False)
            except Exception:
                pass
            self.always_stop = None
            self.always_btn.configure(text="Écoute permanente")
            self._set_status("Écoute permanente arrêtée")
            return
        if sr is None:
            messagebox.showinfo("Micro", "SpeechRecognition n'est pas installé.")
            return
        threading.Thread(target=self._start_always, daemon=True).start()

    def _start_always(self):
        try:
            rec = sr.Recognizer()
            mic = sr.Microphone()
            with mic as source:
                rec.adjust_for_ambient_noise(source, duration=1)

            def callback(recognizer, audio):
                if self.speaking or pc_control.active:
                    return
                try:
                    heard = recognizer.recognize_google(audio, language="fr-FR")
                except sr.UnknownValueError:
                    return
                except Exception as exc:
                    self.ui_queue.put(("status", f"Reconnaissance vocale : {exc}"))
                    return
                if WAKE_SEARCH.search(norm(heard)) or time.time() < self.awake_until:
                    self.ui_queue.put(("heard", heard))

            stop = rec.listen_in_background(mic, callback, phrase_time_limit=10)
            self.ui_queue.put(("always_ready", stop))
        except Exception as exc:
            self.ui_queue.put(("always_error",
                               f"{exc}\n\nVérifie que PyAudio est installé et que le micro est autorisé."))

    def send_message(self):
        text = self.input_var.get().strip()
        if not text or self.busy:
            return
        self.input_var.set("")
        self.process_user_text(text)

    def process_user_text(self, text):
        text = text.strip()
        if not text:
            return
        self._append_chat("Toi", text)
        n = norm(text)
        m = WAKE_SEARCH.search(n)
        if m:
            base = text if len(n) == len(text) else n
            rest = base[m.end():].strip(" ,.!?:;-")
            if not rest:
                self.awake_until = time.time() + 10
                self.say(WAKE_REPLY, remember=False)
                return
            text = rest
        else:
            self.awake_until = 0.0
        self.messages.append({"role": "user", "content": text})
        if self.handle_command(text):
            return
        self.busy = True
        self.send_btn.configure(state="disabled")
        self.entry.configure(state="disabled")
        self._set_status("EVE réfléchit…")
        threading.Thread(target=self._get_ai_reply, args=(list(self.messages),), daemon=True).start()

    def run_async(self, fn, *args, status="…"):
        self._set_status(status)

        def worker():
            try:
                result = fn(*args)
            except Exception as exc:
                result = f"Erreur : {exc}"
            self.ui_queue.put(("say", result, True))
            self.ui_queue.put(("status", "Prête"))

        threading.Thread(target=worker, daemon=True).start()

    def handle_command(self, text):
        self.cfg = load_config()
        n = norm(text).strip()
        n_clean = n.strip(" ?!.,")
        base = text if len(n) == len(text) else n

        if re.fullmatch(r"(bonjour|salut|coucou|hello|bonsoir)( eve)?", n_clean):
            self.say("Salut ! Je suis là. Que puis-je faire pour toi ?")
            return True
        if n_clean in ("aide", "help", "que sais tu faire", "que peux tu faire", "tu sais faire quoi"):
            self.say(HELP_TEXT, remember=False)
            return True
        if re.search(r"\bquelle heure\b", n) or n_clean in ("heure", "donne l heure", "l heure"):
            self.say("Il est " + datetime.now().strftime("%H:%M") + ".")
            return True
        if re.search(r"\b(quelle date|quel jour)\b", n) or n_clean in ("date", "donne la date"):
            self.say("Nous sommes le " + datetime.now().strftime("%d/%m/%Y") + ".")
            return True

        # Contrôle PC (prioritaire, s'arrête dès la fin)
        parsed_ctrl = parse_pc_control(text)
        if parsed_ctrl:
            desc, actions = parsed_ctrl
            self.ui_queue.put(("control_start",))

            def do_ctrl():
                msg = pc_control.run_task(desc, actions)
                self.ui_queue.put(("control_end",))
                return msg

            self.run_async(do_ctrl, status="🎛 Je prends le contrôle du PC…")
            return True

        if re.search(r"\b(prends?\s+le\s+controle|controle\s+(?:le\s+)?pc|fais?\s+a\s+ma\s+place)\b", n):
            self.say(
                "D'accord, je peux prendre le contrôle le temps d'une tâche précise. "
                "Dis-moi quoi faire, par exemple :\n"
                "• « prends le contrôle et ouvre le bloc-notes »\n"
                "• « tape à ma place : bonjour »\n"
                "• « fais une capture d'écran »\n"
                "Dès que j'ai fini, je te rends le contrôle automatiquement.",
                remember=False)
            return True

        # Rappels
        if re.match(r"(?:mets?\s+(?:moi\s+)?un\s+rappel|cree\s+un\s+rappel|rappelle\s+moi|rappeler\s+moi|rappel\b)", n):
            if re.search(r"\b(mes|liste|quels?)\b.*\brappels?\b", n) or n_clean in ("rappels", "mes rappels"):
                return self._list_reminders()
            try:
                due, task = parse_reminder(text)
            except ValueError as exc:
                self.say(str(exc), remember=False)
                return True
            self.reminders.append({"due": due.isoformat(timespec="seconds"), "text": task})
            self._save_reminders()
            when = due.strftime("%H:%M")
            if due.date() != datetime.now().date():
                when += " demain"
            what = f" de {task}" if task else ""
            self.say(f"C'est noté ! Je te rappellerai{what} à {when}.")
            return True
        if re.search(r"\b(mes rappels|liste (?:des |de mes )?rappels|quels sont mes rappels)\b", n):
            return self._list_reminders()
        if re.search(r"\b(supprime|annule|efface|vide)\b.*\brappels?\b", n):
            self.reminders = []
            self._save_reminders()
            self.say("Tous les rappels sont supprimés.")
            return True

        # Lumières
        if re.search(r"\b(lumieres?|lampes?|eclairage|ampoules?)\b", n):
            parsed = parse_light_command(n)
            if parsed is None:
                self.say("Tu veux que j'allume, que j'éteigne, ou que je change la couleur ou l'intensité ?",
                         remember=False)
                return True
            params, confirm = parsed
            lights = Lights(self.cfg["lumieres"])
            if not lights.configured():
                self.say("Mes lumières ne sont pas encore configurées. Clique sur « Config » et indique "
                         "le type (wiz, yeelight, hue ou homeassistant) et l'adresse IP de tes lampes.",
                         remember=False)
                return True

            def do_lights():
                try:
                    lights.apply(**params)
                except Exception as exc:
                    return f"Je n'arrive pas à joindre les lumières : {exc}"
                return confirm
            self.run_async(do_lights, status="Je m'occupe des lumières…")
            return True

        # PC état
        if (re.search(r"\b(pc|ordinateur|processeur|cpu|gpu|carte graphique|machine)\b", n)
                and re.search(r"\b(temperature|chauffe|chaud|etat|charge|ram|memoire|performances?|surveill\w*)\b", n)):
            self.run_async(pc_report, status="Je regarde l'état du PC…")
            return True

        # Satellite
        if re.search(r"satellit|astronaut|iss|station spatiale|survol", n):
            city = extract_city(text, self.cfg["ville"])
            if re.search(r"\bastronaut", n):
                self.run_async(astronauts_report, status="Je regarde qui est dans l'espace…")
            elif re.search(r"\b(survol|prochain|pass)\b", n):
                self.run_async(iss_pass_report, city, status="Je calcule les prochains survols…")
            elif re.search(r"\b(iss|station spatiale)\b", n) and not re.search(r"image|carte|nuage", n):
                self.run_async(iss_report, status="Je cherche la station spatiale…")
            elif re.search(r"\b(image|carte|nuage)\b", n) or re.search(r"satellit", n):
                if re.search(r"\b(tout|complet|rapport)\b", n):
                    self.run_async(satellite_full_report, city, status="Données satellites…")
                else:
                    self.run_async(open_satellite_map, city, status="J'ouvre la carte satellite…")
            else:
                self.run_async(iss_report, status="Je cherche la station spatiale…")
            return True

        # Météo
        if re.search(r"\b(meteo|previsions?|quel temps|temperature|il (?:va )?(?:faire|pleuvoir|neiger))\b", n):
            if re.search(r"\b(pc|ordinateur|cpu|processeur)\b", n):
                self.run_async(pc_report, status="Je regarde l'état du PC…")
                return True
            city = extract_city(text, self.cfg["ville"])
            tomorrow = "demain" in n
            self.run_async(weather_report, city, tomorrow, status="Je regarde la météo…")
            return True

        # Ouvrir une appli
        m = re.match(r"(?:ouvre|ouvrir|lance|lancer|demarre|demarrer)\s+(.+)$", n)
        if m:
            target = base[m.start(1):]

            def do_open():
                result = open_target(target, self.cfg)
                return result or (f"Je ne trouve pas « {target} » parmi tes applis. "
                                  "Tu peux l'ajouter dans « apps_perso » du fichier de config.")
            self.run_async(do_open, status="J'ouvre ça…")
            return True

        # Recherche web
        m = re.match(r"(?:recherche|cherche)\s+(?:sur\s+)?(?:internet|google|le\s+web|le\s+net)\s+(.+)$", n)
        if m:
            query = base[m.start(1):].strip()
            webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(query))
            self.say(f"J'ouvre une recherche sur {query}.")
            return True
        return False

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
        except Exception as exc:
            self._set_status(f"Impossible d'enregistrer les rappels : {exc}")

    def _list_reminders(self):
        if not self.reminders:
            self.say("Tu n'as aucun rappel en attente.", remember=False)
            return True
        items = sorted(self.reminders, key=lambda r: r["due"])
        lines = []
        for r in items:
            due = datetime.fromisoformat(r["due"])
            lines.append(f"• {due.strftime('%d/%m %H:%M')} — {r['text'] or '(sans texte)'}")
        self.say("Tes rappels :\n" + "\n".join(lines), remember=False)
        return True

    def _check_reminders(self):
        now = datetime.now()
        due_now = [r for r in self.reminders if datetime.fromisoformat(r["due"]) <= now]
        if due_now:
            self.reminders = [r for r in self.reminders if r not in due_now]
            self._save_reminders()
            for r in due_now:
                late = (now - datetime.fromisoformat(r["due"])).total_seconds() > 90
                prefix = "⏰ Rappel manqué" if late else "⏰ Rappel"
                self.say(f"{prefix} : {r['text'] or 'tu m’avais demandé un rappel.'}", remember=False)
            try:
                self.root.bell()
                self.root.deiconify()
                self.root.lift()
            except Exception:
                pass
        self.root.after(1000, self._check_reminders)

    def _get_ai_reply(self, history):
        reply = None
        errors = []
        cfg = load_config()
        groq_key = (cfg.get("groq_api_key") or GROQ_API_KEY or "").strip()
        openai_key = (cfg.get("openai_api_key") or ONLINE_API_KEY or "").strip()

        # 1) Pollinations — gratuit, sans clé
        if requests is not None and not reply:
            try:
                user_msgs = [m["content"] for m in history if m["role"] == "user"]
                last = user_msgs[-1] if user_msgs else ""
                prompt = (
                    "Tu es E.V.E., assistant personnel français, utile et concis. "
                    "Réponds uniquement en français, sans préambule.\n\n"
                    f"Utilisateur : {last}\nE.V.E. :"
                )
                url = "https://text.pollinations.ai/" + urllib.parse.quote(prompt)
                r = requests.get(url, timeout=45, headers={"User-Agent": "EVE-Assistant/3.0"})
                if r.ok:
                    text = r.text.strip()
                    if text and len(text) > 2 and not text.lower().startswith("<!doctype"):
                        reply = text
                else:
                    errors.append(f"Pollinations HTTP {r.status_code}")
            except Exception as exc:
                errors.append(f"IA gratuite : {exc}")

        # 2) Groq
        if not reply and groq_key and requests is not None:
            try:
                response = requests.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={"model": GROQ_MODEL, "messages": history, "temperature": 0.7,
                          "max_tokens": 1024},
                    timeout=60)
                response.raise_for_status()
                reply = response.json()["choices"][0]["message"]["content"].strip()
            except Exception as exc:
                errors.append(f"Groq : {exc}")

        # 3) OpenAI
        if not reply and openai_key and requests is not None:
            try:
                response = requests.post(
                    ONLINE_URL,
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json={"model": ONLINE_MODEL, "messages": history, "temperature": 0.7},
                    timeout=60)
                response.raise_for_status()
                reply = response.json()["choices"][0]["message"]["content"].strip()
            except Exception as exc:
                errors.append(f"OpenAI : {exc}")

        # 4) Ollama (optionnel)
        if not reply and requests is not None:
            try:
                response = requests.post(
                    OLLAMA_URL, json={"model": OLLAMA_MODEL, "messages": history, "stream": False},
                    timeout=90)
                response.raise_for_status()
                reply = response.json().get("message", {}).get("content", "").strip()
                if not reply:
                    errors.append("Ollama n'a renvoyé aucune réponse.")
            except Exception as exc:
                errors.append(f"Ollama : {exc}")

        remember = True
        if not reply:
            remember = False
            reply = (
                "Je n'arrive pas à joindre un modèle d'IA pour le moment. "
                "Mes commandes (lumières, météo, satellites, rappels, applis, contrôle PC) "
                "marchent quand même.\n\n"
                "Astuce : pour de meilleures réponses, crée une clé gratuite sur "
                "https://console.groq.com et ajoute-la dans Config (groq_api_key).\n\n"
                "Détails : " + " | ".join(errors[:3])
            )
        self.ui_queue.put(("ai_done", reply, remember))

    def open_config(self):
        cfg = load_config()
        path = str(CONFIG_PATH)
        if not CONFIG_PATH.exists():
            save_config(cfg)
        try:
            if os.name == "nt":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
            self.say(
                "J'ouvre le fichier de configuration. Tu peux y mettre ta ville, "
                "tes lumières, tes applis perso, et éventuellement une clé Groq "
                "(gratuite) ou OpenAI pour de meilleures réponses IA.",
                remember=False)
        except Exception as exc:
            messagebox.showinfo("Config", f"Fichier : {path}\n\n{exc}")

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
            f"Rappels en attente : {len(self.reminders)}",
            f"Fichier de config : {CONFIG_PATH}",
            f"Clé Groq : {'oui' if (cfg.get('groq_api_key') or GROQ_API_KEY) else 'non (IA gratuite utilisée)'}",
            f"Clé OpenAI : {'oui' if (cfg.get('openai_api_key') or ONLINE_API_KEY) else 'non'}",
            f"Modèle Ollama (optionnel) : {OLLAMA_MODEL}",
        ]
        if requests is not None:
            try:
                r = requests.get("http://localhost:11434/api/tags", timeout=2)
                if r.ok:
                    names = [m.get("name", "?") for m in r.json().get("models", [])]
                    lines.append("Ollama : joignable — " + (", ".join(names) if names else "aucun modèle"))
                else:
                    lines.append(f"Ollama : HTTP {r.status_code}")
            except Exception:
                lines.append("Ollama : non lancé (normal — pas obligatoire)")
            try:
                t = requests.get("https://text.pollinations.ai/ping", timeout=5)
                lines.append(f"IA gratuite (Pollinations) : {'OK' if t.ok else 'HTTP ' + str(t.status_code)}")
            except Exception as exc:
                lines.append(f"IA gratuite : injoignable ({exc})")
        messagebox.showinfo("Diagnostic EVE", "\n".join(lines))

    def clear_chat(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._append_chat("EVE", "Discussion effacée. Je suis prête !")

    def _on_close(self):
        if self.always_stop is not None:
            try:
                self.always_stop(wait_for_stop=False)
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    EveApp().run()
