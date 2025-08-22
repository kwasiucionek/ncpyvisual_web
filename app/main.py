from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Tuple
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io, zipfile, time, os, stat, base64, tempfile, re, logging, traceback, subprocess, sys
import configparser
import paramiko
import py7zr
import json
import http.client as httplib
import warnings
from pathlib import Path
import shutil
from datetime import datetime
import hashlib
import uuid

# Ignoruj ostrzeżenia o TripleDES
warnings.filterwarnings("ignore", message=".*TripleDES.*", category=UserWarning)

try:
    from dotenv import load_dotenv
    load_dotenv()
    logging.info("Załadowano zmienne środowiskowe z .env")
except ImportError:
    logging.info("python-dotenv niedostępne, używam zmiennych systemowych")

# Konfiguracja maszyny wirtualnej
VM_HOST = os.getenv("VM_HOST", "192.168.122.228")
VM_USER = os.getenv("VM_HOST_USER", "root")
VM_PASS = os.getenv("VM_HOST_PASS")

# Konfiguracja ncshot
NCSHOT_HOST = VM_HOST
NCSHOT_PORT = int(os.getenv("NCSHOT_PORT", "5543"))

if not VM_PASS:
    logging.warning("⚠ī¸ Brak VM_HOST_PASS w zmiennych środowiskowych!")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('ncpyvisual.log')
    ]
)

# Konfiguracja limitów obrazów (POPRAWIONE LIMITY)
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB maksymalny rozmiar obrazu
MIN_IMAGE_SIZE = 1024  # 1KB minimalny rozmiar dla obrazów głównych
MAX_PLATE_SIZE = 500 * 1024  # 500KB maksymalny rozmiar tablicy
MIN_PLATE_SIZE = 50  # 50 bajtów minimalny rozmiar tablicy

# 🔧 NOWA FUNKCJA: Zabezpieczenie JSON serializacji
def ensure_json_serializable(obj):
    """Konwertuje bytes na string żeby można było serializować do JSON"""
    if isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except UnicodeDecodeError:
            return base64.b64encode(obj).decode('utf-8')
    elif isinstance(obj, dict):
        return {k: ensure_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [ensure_json_serializable(item) for item in obj]
    else:
        return obj

# ===== MODELE =====
class RoiData(BaseModel):
    id: str
    points: List[Dict[str, float]]
    angle: Optional[float] = 0.0
    zoom: Optional[float] = 1.0
    reflexOffsetH: Optional[int] = 0
    reflexOffsetV: Optional[int] = 0
    skewH: Optional[float] = 0.0
    skewV: Optional[float] = 0.0

class DeploymentConfig(BaseModel):
    serialNumber: Optional[str] = ""
    locationId: str
    gpsLat: Optional[str] = None
    gpsLon: Optional[str] = None
    backendAddr: Optional[str] = None
    swdallowMasks: Optional[str] = None
    nativeallowMasks: Optional[str] = None

class FullPackage(BaseModel):
    rois: List[RoiData]
    deployment: DeploymentConfig

class NcshotRequest(BaseModel):
    package: FullPackage
    image_files: List[str]

# ===== APP =====
app = FastAPI(title="NCPyVisual Web Professional")
templates = Jinja2Templates(directory="app/templates")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logging.error(f"⚠ī¸ Błąd walidacji dla {request.url.path}:")
    for error in exc.errors():
        logging.error(f"   - {error['loc']}: {error['msg']} (wartość: {error.get('input', 'brak')})")

    return JSONResponse(
        status_code=422,
        content={
            "detail": "Błąd walidacji danych",
            "errors": exc.errors(),
            "body": str(exc.body) if hasattr(exc, 'body') else None
        }
    )

# ===== ULEPSZONE FUNKCJE PARSOWANIA XML (ze starszej wersji) =====
def safe_float_parse(value: str, default: float = 0.0) -> float:
    """Bezpieczne parsowanie float z domyślną wartością"""
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        logging.warning(f"Nie można sparsować jako float: {value}, używam domyślnej: {default}")
        return default

def safe_int_parse(value: str, default: int = 0) -> int:
    """Bezpieczne parsowanie int z domyślną wartością"""
    try:
        return int(value) if value else default
    except (ValueError, TypeError):
        logging.warning(f"Nie można sparsować jako int: {value}, używam domyślnej: {default}")
        return default

def debug_xml_structure(xml_content: str) -> None:
    """
    Debuguje strukturę XML dla lepszego zrozumienia danych z NCShot
    """
    try:
        root = ET.fromstring(xml_content)
        logging.info("🔍 === DEBUGOWANIE STRUKTURY XML ===")
        logging.info(f"📄 Długość XML: {len(xml_content)} znaków")
        logging.info(f"📋 Root element: {root.tag}")

        def log_element(element, level=0):
            indent = "  " * level
            attrs = f" {element.attrib}" if element.attrib else ""
            text = f" = '{element.text.strip()}'" if element.text and element.text.strip() else ""
            logging.info(f"{indent}📋 {element.tag}{attrs}{text}")

            for child in element:
                log_element(child, level + 1)

        log_element(root)

        # DODATKOWE - sprawdź czy są jakiekolwiek elementy z tekstem
        logging.info("🔍 === SZUKANIE TEKSTU W XML ===")
        all_texts = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                all_texts.append(f"{elem.tag}: {elem.text.strip()}")

        logging.info(f"🔍 Znalezione teksty ({len(all_texts)}):")
        for text in all_texts:
            logging.info(f"  📄 {text}")

        # Szukaj wszystkich wartości w elementach value
        logging.info("🔍 === WSZYSTKIE ELEMENTY VALUE ===")
        value_elements = root.findall(".//value")
        for i, value in enumerate(value_elements):
            name_attr = value.get("name", "no-name")
            text_content = value.text if value.text else "no-text"
            logging.info(f"  🔍 Value {i+1}: name='{name_attr}' text='{text_content}'")

        logging.info("🔍 === KONIEC DEBUGOWANIA XML ===")

    except Exception as e:
        logging.error(f"⚠ī¸ Błąd debugowania XML: {e}")
        # Zapisz surowy XML do logów
        logging.error(f"📄 Surowy XML (pierwsze 1000 znaków): {xml_content[:1000]}")

def process_ncshot_result_xml_enhanced(xml_content: str) -> Dict[str, Any]:
    """
    Rozszerzony parser XML z NCShot - zgodny ze starą aplikacją
    """
    result = {
        "plates": [],
        "vehicles": [],
        "timestamp": None,
        "processing_parameters": {},
        "radar_data": {},
        "signature": None,
        "processing_successful": False,
        "error": None,
        "metadata": {
            "processed_at": datetime.now().isoformat(),
            "xml_length": len(xml_content),
            "parser_version": "3.0.0-enhanced"
        }
    }

    try:
        if not xml_content or not xml_content.strip():
            result["error"] = "Pusta zawartość XML"
            return result

        # DEBUGOWANIE - pokaż całą strukturę XML
        debug_xml_structure(xml_content)

        root = ET.fromstring(xml_content)
        result["metadata"]["root_tag"] = root.tag

        # Parsuj timestamp - jak w starej aplikacji
        timestamp_elem = root.find("timestamp")
        if timestamp_elem is not None:
            try:
                date_elem = timestamp_elem.find("date")
                time_elem = timestamp_elem.find("time")
                ms_elem = timestamp_elem.find("ms")

                if all(e is not None and e.text for e in [date_elem, time_elem, ms_elem]):
                    result["timestamp"] = {
                        "date": date_elem.text.strip(),
                        "time": time_elem.text.strip(),
                        "ms": ms_elem.text.strip()
                    }
            except Exception as e:
                logging.warning(f"Błąd parsowania timestamp: {e}")

        # Parsuj exdata - DOKŁADNIE jak w starej aplikacji
        exdata_elements = root.findall("exdata")
        result["metadata"]["exdata_count"] = len(exdata_elements)

        for exdata_idx, exdata_elem in enumerate(exdata_elements):
            vehicle_data = {
                "exdata_index": exdata_idx,
                "plates": [],  # Lista wariantów tablic dla tego pojazdu
                "vehicle_info": {},
                "parameters": {},
                "signature": None
            }

            for data_elem in exdata_elem.findall("data"):
                try:
                    data_name = data_elem.get("name", "").strip()
                    data_source = data_elem.get("source", "").strip()

                    logging.info(f"    🔍 Przetwarzam data: name='{data_name}', source='{data_source}'")

                    # Zbierz wszystkie wartości
                    data_values = {}
                    for value_elem in data_elem.findall("value"):
                        value_name = value_elem.get("name", "").strip()
                        value_text = value_elem.text.strip() if value_elem.text else ""
                        if value_name:
                            data_values[value_name] = value_text

                    logging.info(f"    📋 Wszystkie wartości w {data_name}: {data_values}")

                    # PARSOWANIE TABLIC - jak w PhotoDescription.py
                    if "plate" in data_name and "trace" not in data_name and data_values:
                        logging.info(f"    🎯 Znaleziono element tablicy: {data_name}")

                        plate_variant = {
                            "country": data_values.get("country", "").strip(),
                            "symbol": data_values.get("symbol", "").strip(),
                            "level": safe_float_parse(data_values.get("level", "0")),
                            "position": data_values.get("position", "").strip(),
                            "prefix": data_values.get("prefix", "").strip(),
                            "type": data_values.get("type", "").strip(),
                            "doubleline": safe_int_parse(data_values.get("doubleline", "0")),
                            "source": data_source,
                            "data_name": data_name,
                            "confidence": safe_float_parse(data_values.get("level", "0")) / 100.0
                        }

                        if plate_variant["symbol"]:
                            logging.info(f"    ✅ Znaleziono tekst tablicy: {plate_variant['symbol']}")
                        if plate_variant["country"]:
                            logging.info(f"    ✅ Znaleziono kraj: {plate_variant['country']}")
                        if plate_variant["level"]:
                            logging.info(f"    ✅ Znaleziono pewność: {plate_variant['level']}%")

                        # Dodaj do listy wariantów tablic dla tego pojazdu
                        vehicle_data["plates"].append(plate_variant)

                        # Dodaj też do głównej listy tablic (dla kompatybilności)
                        result["plates"].append(plate_variant)

                    # PARSOWANIE POJAZDU - jak w starej aplikacji
                    elif data_name == "vehicle" and data_values:
                        logging.info(f"    🚗 Znaleziono informacje o pojeździe")

                        vehicle_info = {
                            "direction": safe_int_parse(data_values.get("direction", "0")),
                            "speed": safe_float_parse(data_values.get("speed", "0")),
                            "estimated_speed": safe_float_parse(data_values.get("estimatedspeed", "0")),
                            "type": data_values.get("type", "").strip(),
                            "manufacturer": data_values.get("manufacturer", "").strip(),
                            "model": data_values.get("model", "").strip(),
                            "color": data_values.get("color", "").strip(),
                            "mmr_pattern_index": safe_int_parse(data_values.get("mmrpatternindex", "0")),
                            "mmr_pattern_divergence": safe_float_parse(data_values.get("mmrpatterndivergence", "0")),
                            "source": data_source
                        }

                        # Oblicz confidence na podstawie divergence
                        divergence = vehicle_info["mmr_pattern_divergence"]
                        if divergence > 0:
                            confidence = max(0.1, 1.0 / (1.0 + divergence))
                        else:
                            confidence = 0.8
                        vehicle_info["confidence"] = confidence

                        vehicle_data["vehicle_info"] = vehicle_info

                        for key, value in vehicle_info.items():
                            if value and key != "confidence":
                                logging.info(f"    ✅ Pojazd {key}: {value}")

                    # PARSOWANIE PARAMETRÓW
                    elif data_name == "parameters":
                        vehicle_data["parameters"] = data_values

                    # PARSOWANIE SYGNATURY
                    elif data_name == "neuralnet" and "signature" in data_values:
                        vehicle_data["signature"] = data_values["signature"]
                        result["signature"] = data_values["signature"]

                    # PARSOWANIE DANYCH RADARU
                    elif data_name == "zur" or "radar" in data_source:
                        result["radar_data"].update(data_values)

                except Exception as e:
                    logging.warning(f"Błąd parsowania elementu data: {e}")
                    continue

            # Dodaj dane pojazdu do wyników
            if vehicle_data["plates"] or vehicle_data["vehicle_info"] or vehicle_data["signature"]:
                result["vehicles"].append(vehicle_data)

        # Określ czy przetwarzanie było udane
        result["processing_successful"] = bool(result["plates"] or result["vehicles"] or result["signature"])

        # Stwórz szczegółowe podsumowanie - jak w starej aplikacji
        result["summary"] = {
            "plates_detected": len(result["plates"]),
            "vehicles_detected": len(result["vehicles"]),
            "has_signature": bool(result["signature"]),
            "has_timestamp": bool(result["timestamp"]),
            "has_radar_data": bool(result["radar_data"]),
            "processing_successful": result["processing_successful"],
            "best_plate_confidence": max([p["confidence"] for p in result["plates"]], default=0.0),
            "plate_variants_total": sum([len(v["plates"]) for v in result["vehicles"]]),
            "exdata_count": len(exdata_elements)
        }

        return result

    except ET.ParseError as e:
        error_msg = f"Błąd parsowania XML: {str(e)}"
        logging.error(error_msg)
        result["error"] = error_msg
        result["error_details"] = {
            "error_type": "xml_parse_error",
            "xml_preview": xml_content[:200] + "..." if len(xml_content) > 200 else xml_content
        }
        return result

    except Exception as e:
        error_msg = f"Błąd przetwarzania danych XML: {str(e)}"
        logging.error(error_msg)
        result["error"] = error_msg
        result["error_details"] = {
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        return result

def extract_detailed_plates_from_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Wyciąga szczegółowe dane tablic z XML w formacie zgodnym ze starą aplikacją"""
    result = process_ncshot_result_xml_enhanced(xml_content)

    detailed_plates = []
    for vehicle in result.get("vehicles", []):
        for plate in vehicle.get("plates", []):
            # Dodaj informacje o pojeździe do tablicy
            enhanced_plate = plate.copy()
            if vehicle.get("vehicle_info"):
                enhanced_plate.update({
                    "vehicle_manufacturer": vehicle["vehicle_info"].get("manufacturer", ""),
                    "vehicle_model": vehicle["vehicle_info"].get("model", ""),
                    "vehicle_color": vehicle["vehicle_info"].get("color", ""),
                    "vehicle_type": vehicle["vehicle_info"].get("type", ""),
                    "vehicle_speed": vehicle["vehicle_info"].get("speed", 0),
                    "mmr_divergence": vehicle["vehicle_info"].get("mmr_pattern_divergence", 0)
                })

            enhanced_plate["exdata_index"] = vehicle["exdata_index"]
            detailed_plates.append(enhanced_plate)

    return detailed_plates

def format_ncshot_summary_enhanced(ncshot_result: Dict[str, Any]) -> str:
    """Formatuje podsumowanie wyników NCShot w stylu starej aplikacji"""
    if not ncshot_result.get("processing_successful"):
        summary = "⚠ī¸ Przetwarzanie nieudane\n"
        error = ncshot_result.get("error", "Nieznany błąd")
        summary += f"🔍 Błąd: {error}\n"
        return summary

    summary = "📊 WYNIKI NCSHOT:\n"

    # Statystyki główne
    plates_count = ncshot_result["summary"]["plates_detected"]
    vehicles_count = ncshot_result["summary"]["vehicles_detected"]
    variants_count = ncshot_result["summary"]["plate_variants_total"]

    summary += f"   🚗 Pojazdy: {vehicles_count}\n"
    summary += f"   🷏ī¸ Tablice główne: {plates_count}\n"
    summary += f"   🔄 Warianty tablic: {variants_count}\n"

    # Najlepsze rozpoznanie
    best_conf = ncshot_result["summary"]["best_plate_confidence"]
    if best_conf > 0:
        conf_icon = "🎯" if best_conf > 0.7 else "⚡" if best_conf > 0.4 else "⚠ī¸"
        summary += f"   {conf_icon} Najlepsze rozpoznanie: {best_conf*100:.1f}%\n"

    # Szczegóły pojazdów
    if ncshot_result["vehicles"]:
        summary += "\n🚙 SZCZEGÓŁY POJAZDÓW:\n"
        for i, vehicle in enumerate(ncshot_result["vehicles"][:3]):  # Pokaż max 3
            summary += f"   Pojazd {i+1}:\n"

            # Info o pojeździe
            if vehicle["vehicle_info"]:
                info = vehicle["vehicle_info"]
                summary += f"      • {info.get('manufacturer', 'N/A')} {info.get('model', 'N/A')}\n"
                summary += f"      • Kolor: {info.get('color', 'N/A')}\n"
                if info.get('speed', 0) > 0:
                    summary += f"      • Prędkość: {info['speed']:.1f} km/h\n"

            # Najlepszy wariant tablicy
            if vehicle["plates"]:
                best_plate = max(vehicle["plates"], key=lambda p: p["confidence"])
                conf_icon = "✅" if best_plate["confidence"] > 0.7 else "⚡" if best_plate["confidence"] > 0.4 else "⚠ī¸"
                summary += f"      {conf_icon} {best_plate['symbol']} ({best_plate['country']}) - {best_plate['level']:.0f}%\n"

    # Timestamp
    if ncshot_result.get("timestamp"):
        ts = ncshot_result["timestamp"]
        summary += f"\n⏰ Czas: {ts['date']} {ts['time']}.{ts['ms']}\n"

    return summary

# ===== ULEPSZONA FUNKCJA GENEROWANIA INI (ZASTĄPIONA) =====
def build_roi_config_ini(package: FullPackage) -> str:
    """
    ULEPSZONA wersja generatora INI - zgodna z wzorcowym WLK.1.079.ini
    """
    config_names = ["main"]
    if len(package.rois) > 1:
        config_names.extend([f"alt{i:02d}" for i in range(1, len(package.rois))])

    # Global section
    ini_content = f"[global]\nconfigurations = {' '.join(config_names)}\n\n"

    # Common section - ROZSZERZONA jak we wzorcu
    ini_content += """[common]
plate.ref.width = 96
required.probability = 0.65
plate.ref.height = 18

"""

    # Configuration sections - dla każdej konfiguracji
    for config_name in config_names:
        ini_content += f"[{config_name}]\n"
        ini_content += f"platerecognizer = platerecognizer-{config_name}\n"
        ini_content += f"classrecognizer = classrecognizer-{config_name}\n\n"

    # Platerecognizer sections - ROZSZERZONE parametry jak we wzorcu
    for i, (config_name, roi) in enumerate(zip(config_names, package.rois)):
        ini_content += f"[platerecognizer-{config_name}]\n"

        # ROI points - konwersja do pikseli (2560x2560 reference)
        if roi.points and len(roi.points) >= 3:
            roi_points_pixels = []
            for p in roi.points:
                # Konwersja względnych współrzędnych (0-1) na piksele lub bezpośrednie użycie
                x = int(float(p['x']) * 2560) if float(p['x']) <= 1.0 else int(float(p['x']))
                y = int(float(p['y']) * 2560) if float(p['y']) <= 1.0 else int(float(p['y']))
                roi_points_pixels.append(f"{x},{y}")
            ini_content += f"roi = {';'.join(roi_points_pixels)}\n"
        else:
            # Domyślny ROI
            default_rois = [
                "395,1263;10,849;7,484;744,413;1944,784",  # main
                "970,1883;289,1132;1703,713;2734,985",     # alt01
                "1378,2330;826,1747;2442,909;2734,996;2746,2324"  # alt02
            ]
            ini_content += f"roi = {default_rois[i] if i < len(default_rois) else default_rois[0]}\n"

        # Podstawowe parametry skalowania
        ini_content += f"skew.h = {float(roi.skewH):.1f}\n"
        ini_content += f"skew.v = {float(roi.skewV):.1f}\n"
        ini_content += f"angle = {float(roi.angle):.1f}\n"

        # Zoom - wartości dopasowane do wzorca
        if config_name == "main":
            zoom_val = float(roi.zoom) if hasattr(roi, 'zoom') and roi.zoom > 0 else 0.04
        elif config_name == "alt01":
            zoom_val = float(roi.zoom) if hasattr(roi, 'zoom') and roi.zoom > 0 else 0.06
        else:
            zoom_val = float(roi.zoom) if hasattr(roi, 'zoom') and roi.zoom > 0 else 0.07
        ini_content += f"zoom = {zoom_val:.2f}\n"

        # ROZSZERZONE PARAMETRY jak we wzorcu WLK.1.079.ini
        if config_name == "main":
            # Główna konfiguracja - pełne parametry
            ini_content += f"filter.gauss = 1\n"
            ini_content += f"autolevel = 5\n"
            ini_content += f"orientation = 0\n"
            ini_content += f"margin.bottom = 0.0\n"
            ini_content += f"margin.right = 0.0\n"
            ini_content += f"margin.top = 0.0\n"
            ini_content += f"margin.left = 0.0\n"
            ini_content += f"recognize.adr = 0\n"  # Domyślnie wyłączone
            ini_content += f"road.background = \n"  # Puste
            ini_content += f"reflex.offset.h = {int(roi.reflexOffsetH) if hasattr(roi, 'reflexOffsetH') else 70}\n"
            ini_content += f"reflex.offset.v = {int(roi.reflexOffsetV) if hasattr(roi, 'reflexOffsetV') else -245}\n"

            # Składnia neuronowa - jak we wzorcu
            ini_content += f"neuronet.syntax.order = +omni (pl de gb cz ua sk at ro by ru nl - bg fr ie es tr) +pl (pl) +baltic (dk ee lv no lt) de (de) by (by) cz (cz) gb (gb) at (at) ua (ua) ru (ru)\n"

            ini_content += f"max.candidates = 5\n"
            ini_content += f"perspective.v = 0.0\n"
            ini_content += f"perspective.h = 0.0\n"
            ini_content += f"required.probability = 0.69\n"
            ini_content += f"anisotropy = 1.0\n"
            ini_content += f"test.analyser = 0\n"
            ini_content += f"country.distribution = \n"  # Puste
            ini_content += f"algorithms = \n"  # Możemy dodać "neuronet.signature" dla niektórych

        ini_content += "\n"

    # Classrecognizer sections - ROZSZERZONE jak we wzorcu
    for i, config_name in enumerate(config_names):
        ini_content += f"[classrecognizer-{config_name}]\n"

        # Referencje do platerecognizer
        for param in ['skew.h', 'skew.v', 'angle', 'zoom']:
            ini_content += f"{param} = %(platerecognizer-{config_name}/{param})\n"

        # DODATKOWE PARAMETRY jak we wzorcu
        if config_name == "main":
            ini_content += f"foreshort.h = -0.0003\n"
            ini_content += f"anisotropy = 1.15\n"
            ini_content += f"local.contrast.normalization = 1.9\n"
            ini_content += f"rotation.correction.threshold = 0.0\n"
            ini_content += f"perspective.v = %(platerecognizer-{config_name}/perspective.v)\n"
            ini_content += f"perspective.h = %(platerecognizer-{config_name}/perspective.h)\n"
            ini_content += f"zoom.correction = 1\n"

        ini_content += "\n"

    return ini_content

# ===== POPRAWIONE FUNKCJE WALIDACJI OBRAZÓW =====
def validate_image_data(image_data: bytes, image_index: int, is_plate: bool = False) -> bool:
    """Waliduje dane obrazu przed wysłaniem do NCShot z obsługą tablic"""

    # Różne limity dla obrazów głównych vs tablic
    min_size = MIN_PLATE_SIZE if is_plate else MIN_IMAGE_SIZE
    max_size = MAX_PLATE_SIZE if is_plate else MAX_IMAGE_SIZE

    # Sprawdź rozmiar
    if len(image_data) < min_size:
        logging.error(f"⚠ī¸ {'Tablica' if is_plate else 'Obraz'} {image_index}: zbyt mała ({len(image_data)} bajtów)")
        return False

    if len(image_data) > max_size:
        logging.error(f"⚠ī¸ {'Tablica' if is_plate else 'Obraz'} {image_index}: zbyt duża ({len(image_data)} bajtów > {max_size})")
        return False

    # Sprawdź nagłówek JPEG (mniej rygorystycznie dla tablic)
    if not image_data.startswith(b'\xff\xd8'):
        if is_plate:
            logging.warning(f"⚠ī¸ Tablica {image_index}: brak nagłówka JPEG, ale kontynuję")
        else:
            logging.error(f"⚠ī¸ Obraz {image_index}: nieprawidłowy nagłówek JPEG")
            return False

    # Sprawdź końcówkę JPEG (mniej rygorystycznie dla tablic)
    if not image_data.endswith(b'\xff\xd9'):
        if is_plate:
            logging.warning(f"⚠ī¸ Tablica {image_index}: brak końcówki JPEG, ale kontynuę (tablice często są niepełne)")
        else:
            logging.warning(f"⚠ī¸ Obraz {image_index}: brak końcówki JPEG, ale kontynuę")

    logging.info(f"✅ {'Tablica' if is_plate else 'Obraz'} {image_index}: walidacja przeszła pomyślnie ({len(image_data)} bajtów)")
    return True

def optimize_image_for_ncshot(image_data: bytes) -> bytes:
    """Optymalizuje obraz dla NCShot (jeśli potrzeba)"""
    # Jeśli obraz jest za duży, możemy w przyszłości dodać kompresję
    # Na razie tylko zwracamy oryginalny
    return image_data

# ===== POPRAWIONE FUNKCJE POBIERANIA TABLIC =====
def test_plate_endpoints(token: str) -> List[Tuple[str, int, str]]:
    """Testuje różne możliwe endpointy dla obrazów tablic - z lepszą obsługą błędów"""
    possible_endpoints = [
        # Standardowe endpointy
        f"/vehicleplate?token={token}&number=1",
        f"/plate?token={token}&number=1",
        f"/plateimage?token={token}&number=1",
        f"/plateimg?token={token}&number=1",
        f"/image?token={token}&number=1",
        f"/img?token={token}&number=1",

        # Endpointy bez number
        f"/vehicleplate?token={token}",
        f"/plate?token={token}",
        f"/plateimage?token={token}",
        f"/plateimg?token={token}",
        f"/image?token={token}",
        f"/img?token={token}",

        # Endpointy z różnymi parametrami
        f"/vehicleplate/{token}/1",
        f"/plate/{token}/1",
        f"/plateimage/{token}/1",
        f"/plateimg/{token}/1",

        # Endpointy z index zamiast number
        f"/vehicleplate?token={token}&index=1",
        f"/plate?token={token}&index=1",
        f"/plateimage?token={token}&index=1",

        # Endpointy z id zamiast number
        f"/vehicleplate?token={token}&id=1",
        f"/plate?token={token}&id=1"
    ]

    working_endpoints = []

    for endpoint in possible_endpoints:
        try:
            test_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=10)
            test_hc.request("GET", endpoint)
            test_resp = test_hc.getresponse()
            test_data = test_resp.read()
            test_hc.close()

            if test_resp.status == 200:
                if test_data and len(test_data) > 0:
                    if test_data.startswith(b'\xff\xd8'):
                        working_endpoints.append((endpoint, len(test_data), "JPEG"))
                        logging.info(f"✅ DZIAŁAJĄCY ENDPOINT: {endpoint} -> {len(test_data)} bajtów JPEG")
                    else:
                        working_endpoints.append((endpoint, len(test_data), "nie-JPEG"))
                        logging.info(f"⚠ī¸ DZIAŁAJĄCY ale nie JPEG: {endpoint} -> {len(test_data)} bajtów")
                else:
                    logging.debug(f"⚠ī¸ {endpoint} zwrócił 200 ale bez danych")
            elif test_resp.status == 404:
                logging.debug(f"⚠ī¸ {endpoint}: 404")
            else:
                logging.debug(f"⚠ī¸ {endpoint}: {test_resp.status}")

        except Exception as e:
            logging.debug(f"⚠ī¸ {endpoint}: EXCEPTION {e}")

    return working_endpoints

# 🔧 ULEPSZONA FUNKCJA POBIERANIA TABLIC z natychmiastowym zwolnieniem
def get_plates_from_ncshot_enhanced_with_immediate_release(token: str, xml_content: str, parsed_xml: Dict[str, Any], image_index: int) -> List[str]:
    """
    Ulepszona funkcja pobierania tablic z NATYCHMIASTOWYM zarządzaniem pamięcią
    """
    plates = []

    try:
        expected_plates = len(parsed_xml.get("vehicles", []))

        if expected_plates == 0:
            return []

        # Test podstawowego endpointu
        try:
            test_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=5)
            test_hc.request("GET", f"/vehicleplate?token={token}&number=1")
            test_resp = test_hc.getresponse()
            test_data = test_resp.read()
            test_hc.close()

            if test_resp.status == 404:
                logging.warning(f"⚠ī¸ NCShot nie udostępnia endpointów obrazów tablic (404)")
                return [None] * expected_plates
            elif test_resp.status >= 500:
                logging.warning(f"⚠ī¸ NCShot ma problemy z generowaniem obrazów tablic (status: {test_resp.status})")
                return [None] * expected_plates

        except Exception as e:
            logging.warning(f"⚠ī¸ Test endpointu tablic nieudany: {e}")
            return [None] * expected_plates

        # Pobierz obrazy tablic
        for j in range(1, expected_plates + 1):
            try:
                plate_url = f"/vehicleplate?token={token}&number={j}"
                logging.info(f"📸 Pobieranie tablicy {j} z: {plate_url}")

                # 🔧 NOWE POŁĄCZENIE dla każdej tablicy (bezpieczniejsze)
                plate_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=15)
                plate_hc.request("GET", plate_url)
                plate_resp = plate_hc.getresponse()
                plate_data = plate_resp.read()
                plate_hc.close()  # 🔧 NATYCHMIAST ZAMKNIJ

                if plate_resp.status == 200 and plate_data and validate_image_data(plate_data, j, is_plate=True):
                    plate_b64 = base64.b64encode(plate_data).decode('utf-8')
                    plate_image = f"data:image/jpeg;base64,{plate_b64}"
                    plates.append(plate_image)
                    logging.info(f"✅ Pobrano tablicę {j}: {len(plate_data)} bajtów")
                else:
                    plates.append(None)
                    if plate_resp.status != 200:
                        logging.warning(f"⚠ī¸ Tablica {j}: status={plate_resp.status}")
                    else:
                        logging.warning(f"⚠ī¸ Tablica {j} nie przeszła walidacji")

                # 🔧 WYMUŚ CZYSZCZENIE po każdej tablicy
                del plate_data

            except Exception as plate_error:
                logging.error(f"⚠ī¸ EXCEPTION tablica {j}: {plate_error}")
                plates.append(None)

        logging.info(f"📊 Pobrano {len([p for p in plates if p])} z {len(plates)} tablic dla obrazu {image_index}")
        return plates

    except Exception as e:
        logging.error(f"⚠ī¸ Błąd analizy XML dla tablic obrazu {image_index}: {e}")
        return []

# 🔧 NOWA FUNKCJA: Główna funkcja pobierania tablic (wrapper)
def get_plates_from_ncshot_enhanced(token: str, xml_content: str, parsed_xml: Dict[str, Any], image_index: int) -> List[str]:
    """
    Pobiera obrazy tablic z NCShot z lepszym zarządzaniem połączeniami
    """
    return get_plates_from_ncshot_enhanced_with_immediate_release(token, xml_content, parsed_xml, image_index)

def assign_plate_images_to_data(detailed_plates: List[Dict[str, Any]], plate_images: List[str]) -> List[Dict[str, Any]]:
    """
    Przypisuje obrazy tablic do szczegółowych danych
    """
    result = []

    for i, plate_data in enumerate(detailed_plates):
        enhanced_plate = plate_data.copy()

        # Przypisz obraz tablicy jeśli dostępny
        if i < len(plate_images) and plate_images[i]:
            enhanced_plate["plate_image"] = plate_images[i]
            enhanced_plate["has_image"] = True
        else:
            enhanced_plate["plate_image"] = None
            enhanced_plate["has_image"] = False

        result.append(enhanced_plate)

    return result

# ===== SSH FUNKCJE =====
def create_ssh_connection(host, username, password, timeout=30):
    """Tworzy bezpieczne połączenie SSH"""
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': host,
            'username': username,
            'password': password,
            'timeout': timeout,
            'allow_agent': False,
            'look_for_keys': False,
            'banner_timeout': 30
        }

        logging.info(f"🔗 Łączenie z {username}@{host}...")
        client.connect(**connect_kwargs)
        logging.info(f"✅ Połączono z {host}")
        return client
    except paramiko.AuthenticationException:
        raise HTTPException(status_code=401, detail=f"Błąd uwierzytelnienia dla {host}")
    except paramiko.SSHException as e:
        raise HTTPException(status_code=500, detail=f"Błąd SSH: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd połączenia z {host}: {str(e)}")

def open_via_jump(device_ip: str, device_pass: Optional[str]) -> Tuple[paramiko.SSHClient, paramiko.SSHClient]:
    """Połączenie przez jump host"""
    JUMP_HOST = "10.10.33.113"
    JUMP_USER = os.getenv("JUMP_HOST_USER")
    JUMP_PASS = os.getenv("JUMP_HOST_PASS")

    if not JUMP_USER or not JUMP_PASS:
        raise HTTPException(status_code=500, detail="Brak konfiguracji JUMP_HOST_USER/JUMP_HOST_PASS.")

    jump = None
    dev = None

    try:
        # Połączenie z jump hostem
        jump = create_ssh_connection(JUMP_HOST, JUMP_USER, JUMP_PASS)

        # Tunelowanie do urządzenia
        logging.info(f"🚇 Tworzenie tunelu do {device_ip}...")
        transport = jump.get_transport()
        dest_addr = (device_ip, 22)
        local_addr = ('127.0.0.1', 0)
        channel = transport.open_channel("direct-tcpip", dest_addr, local_addr)

        # Połączenie z urządzeniem przez tunel
        dev = paramiko.SSHClient()
        dev.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': device_ip,
            'sock': channel,
            'username': "root",
            'password': device_pass,
            'timeout': 30,
            'allow_agent': False,
            'look_for_keys': False
        }

        dev.connect(**connect_kwargs)
        logging.info(f"✅ Połączono z urządzeniem {device_ip}")
        return jump, dev

    except Exception as e:
        # Cleanup w przypadku błędu
        if dev:
            try:
                dev.close()
            except:
                pass
        if jump:
            try:
                jump.close()
            except:
                pass
        raise

def connect_to_vm() -> paramiko.SSHClient:
    """Połączenie bezpośrednio z maszyną wirtualną"""
    if not VM_PASS:
        raise HTTPException(status_code=500, detail="Brak konfiguracji VM_HOST_PASS")
    return create_ssh_connection(VM_HOST, VM_USER, VM_PASS)

def execute_and_log(dev: paramiko.SSHClient, command: str) -> Tuple[str, str]:
    logging.info(f"🖥ī¸ Wykonuję: {command}")
    try:
        stdin, stdout, stderr = dev.exec_command(command, timeout=30)
        stdout_str = stdout.read().decode('utf-8', 'ignore').strip()
        stderr_str = stderr.read().decode('utf-8', 'ignore').strip()

        if stdout_str:
            logging.info(f"  ✅ [STDOUT]: {stdout_str[:200]}{'...' if len(stdout_str) > 200 else ''}")
        if stderr_str:
            logging.warning(f"  ⚠ī¸ [STDERR]: {stderr_str[:200]}{'...' if len(stderr_str) > 200 else ''}")

        return stdout_str, stderr_str
    except Exception as e:
        logging.error(f"  ⚠ī¸ Błąd wykonania komendy: {e}")
        return "", str(e)

# ===== GŁÓWNA ULEPSZONA FUNKCJA NCSHOT =====
def start_ncshot_with_config_safe(package: FullPackage, image_files: List[str]) -> Dict[str, Any]:
    """
    NAPRAWIONA WERSJA - zarządzanie pamięcią na podstawie starego kodu
    """
    logging.info(f"🚀 === NCSHOT PROFESSIONAL - NAPRAWIONA WERSJA PAMIĘCI ===")
    logging.info(f"   🏠 VM: {NCSHOT_HOST}:{NCSHOT_PORT}")
    logging.info(f"   🖼ī¸ Liczba obrazów: {len(image_files)}")
    logging.info(f"   🎯 Liczba ROI: {len(package.rois)}")

    vm_ssh = None
    try:
        # 1. Połącz się z maszyną wirtualną przez SSH
        vm_ssh = connect_to_vm()
        vm_sftp = vm_ssh.open_sftp()

        # 2. Wygeneruj konfigurację INI
        ini_config = build_roi_config_ini(package)
        logging.info(f"📋 Wygenerowana konfiguracja INI ({len(ini_config)} znaków)")

        # 3. Skopiuj konfigurację na maszynę wirtualną
        config_path = "/neurocar/etc/ncshot.d/tmp.ini"
        logging.info(f"📤 Kopiuję konfigurację do: {config_path}")

        execute_and_log(vm_ssh, "mkdir -p /neurocar/etc/ncshot.d")
        vm_sftp.putfo(io.BytesIO(ini_config.encode('utf-8')), config_path)

        vm_sftp.close()
        vm_ssh.close()
        vm_ssh = None

        # 4. Test dostępności NCShot
        logging.info(f"🏠 Sprawdzanie dostępności NCShot HTTP API...")
        try:
            test_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=10)
            test_hc.request("GET", "/")
            test_resp = test_hc.getresponse()
            test_resp.read()  # Przeczytaj response
            test_hc.close()
            logging.info(f"✅ NCShot HTTP API odpowiada: {test_resp.status}")
        except Exception as e:
            logging.error(f"⚠ī¸ NCShot HTTP API nie odpowiada: {e}")
            raise HTTPException(status_code=503, detail=f"NCShot nie jest dostępny: {e}")

        # 5. Wyślij konfigurację przez HTTP
        try:
            logging.info("📤 Wysyłam konfigurację do NCShot przez HTTP API...")
            config_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=30)
            config_hc.request("PUT", "/config/tmp", ini_config.encode('utf-8'), {
                "Content-Type": "text/plain",
                "Content-Length": str(len(ini_config.encode('utf-8')))
            })
            config_resp = config_hc.getresponse()
            config_content = config_resp.read()
            config_hc.close()

            if config_resp.status != 200:
                logging.error(f"⚠ī¸ NCShot odrzucił konfigurację: {config_resp.status}")
                raise HTTPException(status_code=500, detail=f"NCShot odrzucił konfigurację")
            else:
                logging.info("✅ Konfiguracja zaakceptowana przez NCShot")
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"⚠ī¸ Błąd wysyłania konfiguracji przez HTTP: {e}")
            raise HTTPException(status_code=500, detail=f"Błąd konfiguracji NCShot: {e}")

        # 6. GŁÓWNE PRZETWARZANIE - ALGORYTM ZE STAREGO KODU
        result = {}
        failed_images = 0
        total_plates = 0
        total_vehicles = 0

        # KLUCZOWA ZMIANA: Przetwarzaj obrazy PO JEDNYM (jak w starym kodzie)
        for i, image_b64 in enumerate(image_files):
            try:
                logging.info(f"🖼ī¸ === PRZETWARZANIE OBRAZU {i+1}/{len(image_files)} ===")

                # 🔧 BEZPIECZNE dekodowanie obrazu
                try:
                    if image_b64.startswith('data:image'):
                        header, data = image_b64.split(',', 1)
                        image_data = base64.b64decode(data)
                    else:
                        image_data = base64.b64decode(image_b64)

                    if not validate_image_data(image_data, i):
                        failed_images += 1
                        continue

                except Exception as e:
                    logging.error(f"⚠ī¸ Błąd dekodowania obrazu {i}: {e}")
                    failed_images += 1
                    continue

                logging.info(f"📊 Wysyłanie obrazu: {len(image_data)} bajtów")

                # 🔧 KLUCZOWA ZMIANA: NOWE POŁĄCZENIE dla każdego obrazu (jak w starym kodzie)
                hc = None
                token = None
                try:
                    hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=60)

                    # 🔧 BEZPIECZNE wysyłanie
                    hc.request("PUT", "/tmp?anpr=1&mmr=1&diagnostic=1", image_data, {
                        "Content-Type": "image/jpeg",
                        "Content-Length": str(len(image_data))
                    })
                    resp = hc.getresponse()

                    logging.info(f"📨 Odpowiedź dla obrazu {i}: {resp.status} {resp.reason}")

                    if resp.status != 200:
                        error_content = resp.read()
                        hc.close()
                        logging.error(f"⚠ī¸ Błąd przetwarzania obrazu {i}: {resp.status}")

                        # 🔧 WAŻNE: Przerwij przy błędzie pamięci
                        if b"bad_alloc" in error_content or resp.status >= 500:
                            logging.error("💥 Wykryto błąd pamięci w NCShot - przerywam przetwarzanie")
                            break

                        failed_images += 1
                        continue

                    token = resp.getheader("ncshot-token")
                    xml_content = resp.read()

                    # 🔧 KONWERTUJ NA STRING JEŚLI TO BYTES
                    if isinstance(xml_content, bytes):
                        xml_content = xml_content.decode('utf-8')

                    hc.close()  # 🔧 ZAMKNIJ od razu po odebraniu XML

                    if token:
                        logging.info(f"🎫 Otrzymano token: {token}")

                    logging.info(f"📄 Otrzymano XML ({len(xml_content)} znaków)")

                    # Parsuj XML
                    parsed_xml = process_ncshot_result_xml_enhanced(xml_content)

                    file_result = {
                        "xml": xml_content,  # Już jest stringiem po konwersji
                        "plates": [],
                        "parsed_data": parsed_xml,
                        "detailed_plates": extract_detailed_plates_from_xml(xml_content),
                        "summary": format_ncshot_summary_enhanced(parsed_xml)
                    }

                    # Aktualizuj statystyki
                    if parsed_xml["processing_successful"]:
                        total_plates += parsed_xml["summary"]["plates_detected"]
                        total_vehicles += parsed_xml["summary"]["vehicles_detected"]

                    # 🔧 POBIERZ TABLICE i ZWOLNIJ TOKEN od razu
                    if token:
                        try:
                            plates = get_plates_from_ncshot_enhanced(token, xml_content, parsed_xml, i)
                            file_result["plates"] = plates
                            file_result["detailed_plates_with_images"] = assign_plate_images_to_data(
                                file_result["detailed_plates"], plates
                            )
                        except Exception as plate_error:
                            logging.error(f"⚠ī¸ Błąd pobierania tablic: {plate_error}")
                            file_result["plates"] = []

                        # 🔧 NATYCHMIAST ZWOLNIJ TOKEN (krytyczne dla pamięci)
                        try:
                            release_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=10)
                            release_hc.request("GET", f"/release?token={token}")
                            release_resp = release_hc.getresponse()
                            release_resp.read()
                            release_hc.close()
                            logging.info(f"🗑ī¸ Token {token} zwolniony natychmiast")
                        except Exception as release_error:
                            logging.error(f"⚠ī¸ KRYTYCZNY: Błąd zwalniania tokenu {token}: {release_error}")
                            # To jest krytyczne - token nie zwolniony = przeciek pamięci

                    result[f"image_{i}"] = file_result

                    # 🔧 WYMUŚ CZYSZCZENIE PAMIĘCI po każdym obrazie
                    import gc
                    del image_data  # Jawnie usuń duże dane
                    gc.collect()    # Wymuś garbage collection

                except Exception as e:
                    logging.error(f"⚠ī¸ KRYTYCZNY BŁĄD obrazu {i}: {e}")
                    if hc:
                        try:
                            hc.close()
                        except:
                            pass
                    if token:
                        # Zawsze próbuj zwolnić token nawet przy błędzie
                        try:
                            release_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=5)
                            release_hc.request("GET", f"/release?token={token}")
                            release_resp = release_hc.getresponse()
                            release_resp.read()
                            release_hc.close()
                            logging.info(f"🗑ī¸ Token {token} zwolniony po błędzie")
                        except:
                            logging.error(f"⚠ī¸ KRYTYCZNY: Nie udało się zwolnić tokenu {token} po błędzie")

                    failed_images += 1
                    continue

            except Exception as e:
                logging.error(f"⚠ī¸ BŁĄD ZEWNĘTRZNY obrazu {i}: {e}")
                failed_images += 1
                continue

        # 🔧 WYMUŚ OSTATECZNE CZYSZCZENIE PAMIĘCI
        import gc
        gc.collect()

        logging.info(f"✅ === NCSHOT PROFESSIONAL ZAKOŃCZONY ===")
        logging.info(f"   📊 Pomyślnie: {len(result)} obrazów")
        logging.info(f"   ⚠ī¸ Błędy: {failed_images} obrazów")
        logging.info(f"   🚗 Pojazdy: {total_vehicles}")
        logging.info(f"   🷏ī¸ Tablice: {total_plates}")

        # Rozszerzone statystyki
        result["_stats"] = {
            "processed": len(result) - 1,
            "failed": failed_images,
            "total": len(image_files),
            "total_vehicles": total_vehicles,
            "total_plates": total_plates,
            "processing_time": datetime.now().isoformat(),
            "success_rate": (len(result) - 1) / len(image_files) * 100 if image_files else 0,
            "memory_management": "improved_with_immediate_token_release"
        }

        return result

    except Exception as e:
        logging.error(f"⚠ī¸ KRYTYCZNY BŁĄD NCShot: {e}")
        # 🔧 Cleanup przy błędzie
        import gc
        gc.collect()
        raise e
    finally:
        if vm_ssh:
            vm_ssh.close()

# ===== POPRAWIONA FUNKCJA POBIERANIA OBRAZÓW Z URZĄDZENIA =====
def fetch_images_from_device(device_ip: str, device_pass: Optional[str], count: int) -> List[Dict[str,str]]:
    """
    POPRAWIONA: Pobiera obrazy ze WSZYSTKICH katalogów, nie tylko z najnowszego
    """
    jump = dev = None
    try:
        jump, dev = open_via_jump(device_ip, device_pass)
        sftp = dev.open_sftp()
        base = "/neurocar/data/deleted"

        # Pobierz wszystkie katalogi
        items = sftp.listdir_attr(base)
        dirs = [d for d in items if stat.S_ISDIR(d.st_mode)]
        if not dirs:
            logging.warning("⚠ī¸ Brak katalogów w /neurocar/data/deleted")
            return []

        logging.info(f"🔍 Znaleziono {len(dirs)} katalogów: {[d.filename for d in dirs]}")

        # 🔧 NOWE: Zbierz pliki ze WSZYSTKICH katalogów
        all_files = []
        processed_dirs = 0

        # Sortuj katalogi chronologicznie (najnowsze najpierw)
        sorted_dirs = sorted(dirs, key=lambda d: d.st_mtime, reverse=True)

        for dir_attr in sorted_dirs:
            try:
                folder_path = f"{base}/{dir_attr.filename}"
                logging.info(f"📂 Sprawdzanie katalogu: {dir_attr.filename}")

                # Pobierz pliki z tego katalogu
                try:
                    folder_files = sftp.listdir_attr(folder_path)
                    seven_zip_files = [f for f in folder_files if f.filename.endswith('.7z')]

                    logging.info(f"   📦 Znaleziono {len(seven_zip_files)} plików .7z")

                    # Dodaj informację o katalogu do każdego pliku
                    for file_attr in seven_zip_files:
                        all_files.append({
                            'attr': file_attr,
                            'folder': dir_attr.filename,
                            'full_path': f"{folder_path}/{file_attr.filename}",
                            'mtime': file_attr.st_mtime
                        })

                    processed_dirs += 1

                    # Przerwij jeśli mamy już więcej niż potrzeba (optymalizacja)
                    if len(all_files) >= count * 2:  # Zapas x2
                        logging.info(f"   ⚡ Znaleziono wystarczająco plików ({len(all_files)}), przerywam skanowanie")
                        break

                except Exception as folder_error:
                    logging.warning(f"   ⚠ī¸ Błąd skanowania katalogu {dir_attr.filename}: {folder_error}")
                    continue

            except Exception as e:
                logging.warning(f"⚠ī¸ Błąd przetwarzania katalogu {dir_attr.filename}: {e}")
                continue

        if not all_files:
            logging.warning("⚠ī¸ Nie znaleziono żadnych plików .7z we wszystkich katalogach")
            return []

        # Sortuj wszystkie pliki globalnie po czasie (najnowsze najpierw)
        all_files.sort(key=lambda x: x['mtime'], reverse=True)

        # Weź tylko tyle ile potrzeba
        files_to_process = all_files[:count]

        logging.info(f"🎯 Przetwarzanie {len(files_to_process)} najnowszych plików z {processed_dirs} katalogów:")
        for i, file_info in enumerate(files_to_process):
            logging.info(f"   {i+1}. {file_info['folder']}/{file_info['attr'].filename}")

        # 🔧 PRZETWARZANIE PLIKÓW (pozostaje bez zmian)
        imgs = []
        for i, file_info in enumerate(files_to_process):
            try:
                file_path = file_info['full_path']
                file_attr = file_info['attr']
                folder_name = file_info['folder']

                logging.info(f"📦 Przetwarzanie ({i+1}/{len(files_to_process)}): {file_path}")

                # Pobierz plik
                with sftp.open(file_path, 'rb') as f:
                    data = f.read()

                logging.info(f"   📊 Pobrano: {len(data)} bajtów")

                # Wyodrębnij obraz z archiwum 7z
                buf = io.BytesIO(data)
                image_bytes = None
                original_format = None

                try:
                    with py7zr.SevenZipFile(buf, mode='r') as z:
                        file_list = z.list()
                        target_filename = None

                        # Znajdź plik obrazu w archiwum
                        for file_info_7z in file_list:
                            if file_info_7z.filename.lower().endswith(('.jpg', '.jpeg', '.bif', '.zur')):
                                target_filename = file_info_7z.filename
                                original_format = os.path.splitext(file_info_7z.filename)[1].lower()
                                break

                        if target_filename:
                            logging.info(f"   🖼ī¸ Znaleziono obraz: {target_filename} ({original_format})")

                            with tempfile.TemporaryDirectory() as temp_dir:
                                z.extractall(path=temp_dir)
                                temp_file_path = os.path.join(temp_dir, target_filename)

                                if os.path.exists(temp_file_path):
                                    with open(temp_file_path, 'rb') as img_file:
                                        image_bytes = img_file.read()

                                    # WALIDACJA OBRAZU
                                    if validate_image_data(image_bytes, len(imgs)):
                                        # Utwórz unikalną nazwę z informacją o katalogu
                                        display_filename = f"{folder_name}_{file_attr.filename}"

                                        imgs.append({
                                            "filename": display_filename,
                                            "data": "data:image/jpeg;base64,"+base64.b64encode(image_bytes).decode('utf-8'),
                                            "size": len(image_bytes),
                                            "original_format": original_format,
                                            "source_folder": folder_name,
                                            "archive_name": file_attr.filename
                                        })
                                        logging.info(f"   ✅ Dodano obraz: {display_filename} ({len(image_bytes)} bajtów)")
                                    else:
                                        logging.warning(f"   ⚠ī¸ Odrzucono nieprawidłowy obraz: {target_filename}")
                                else:
                                    logging.warning(f"   ⚠ī¸ Nie znaleziono wyodrębnionego pliku: {temp_file_path}")
                        else:
                            logging.warning(f"   ⚠ī¸ Brak plików obrazów w archiwum {file_attr.filename}")

                except Exception as extract_error:
                    logging.error(f"   ⚠ī¸ Błąd przy dekompresji {file_attr.filename}: {extract_error}")
                    continue

            except Exception as file_error:
                logging.error(f"⚠ī¸ Błąd przetwarzania pliku {file_info['full_path']}: {file_error}")
                continue

        logging.info(f"✅ Pobrano {len(imgs)} obrazów z {processed_dirs} katalogów")

        # Dodaj statystyki
        if imgs:
            folders_used = set(img.get('source_folder', 'unknown') for img in imgs)
            logging.info(f"📊 Użyte katalogi: {list(folders_used)}")

        sftp.close()
        return imgs

    except Exception as e:
        logging.error(f"💥 Krytyczny błąd pobierania obrazów: {e}")
        return []
    finally:
        if dev:
            dev.close()
        if jump:
            jump.close()

def get_device_config(device_ip: str, device_pass: Optional[str]) -> Dict[str, Any]:
    jump = dev = None
    try:
        jump, dev = open_via_jump(device_ip, device_pass)
        sftp = dev.open_sftp()
        with sftp.open("/neurocar/etc/location.ini") as f:
            content = f.read().decode('utf-8')
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read_string(content)

        out = {
            "serialNumber": cfg.get("expect","serialno", fallback=""),
            "locationId": cfg.get("location","client.id", fallback=""),
            "gpsLat": cfg.get("location","default.lat", fallback=""),
            "gpsLon": cfg.get("location","default.lon", fallback=""),
            "backendAddr": cfg.get("location","backend.addr", fallback=""),
            "swdallowMasks": cfg.get("location","swdallow.masks", fallback=""),
            "nativeallowMasks": cfg.get("location","nativeallow.masks", fallback=""),
        }

        rois = []
        if out["locationId"]:
            p = f"/neurocar/etc/ncshot.d/{out['locationId']}.ini"
            try:
                with sftp.open(p) as f:
                    nc = f.read().decode('utf-8')
                ncfg = configparser.ConfigParser(interpolation=None)
                ncfg.read_string(nc)

                for sec in ncfg.sections():
                    if sec.lower().startswith('platerecognizer-'):
                        pts = ncfg.get(sec, 'roi', fallback='')
                        pts_list = [{"x": float(p.split(',')[0]), "y": float(p.split(',')[1])} for p in pts.split(';')] if pts else []
                        rois.append({
                            "id": f"ROI-{sec.split('-')[-1].upper()}",
                            "points": pts_list,
                            "angle": ncfg.getfloat(sec, 'angle', fallback=0),
                            "zoom": ncfg.getfloat(sec, 'zoom', fallback=1.0),
                            "reflexOffsetH": ncfg.getint(sec, 'reflex.offset.h', fallback=0),
                            "reflexOffsetV": ncfg.getint(sec, 'reflex.offset.v', fallback=0),
                            "skewH": ncfg.getfloat(sec, 'skew.h', fallback=0),
                            "skewV": ncfg.getfloat(sec, 'skew.v', fallback=0),
                        })
            except FileNotFoundError:
                logging.warning(f"Plik ROI {p} nie został znaleziony, import bez ROI.")

        out["rois"] = rois
        sftp.close()
        return out
    finally:
        if dev:
            dev.close()
        if jump:
            jump.close()

# ===== NOWE FUNKCJE: XML SCENA =====
def build_scene_xml(package: FullPackage, image_data: str = None) -> str:
    """
    Generuje XML z konfiguracją sceny - gotowy do zapisu
    """
    # Root element
    root = ET.Element("scene")
    root.set("version", "3.2.0-enhanced")
    root.set("created", datetime.now().isoformat())

    # Metadata
    metadata = ET.SubElement(root, "metadata")
    ET.SubElement(metadata, "application").text = "NCPyVisual"
    ET.SubElement(metadata, "version").text = "3.2.0-ultimate-enhanced"
    ET.SubElement(metadata, "description").text = "Scena wygenerowana przez NCPyVisual"

    # Location info
    location = ET.SubElement(root, "location")
    ET.SubElement(location, "id").text = package.deployment.locationId or ""
    ET.SubElement(location, "serial_number").text = package.deployment.serialNumber or ""

    if package.deployment.gpsLat and package.deployment.gpsLon:
        gps = ET.SubElement(location, "gps")
        ET.SubElement(gps, "latitude").text = package.deployment.gpsLat
        ET.SubElement(gps, "longitude").text = package.deployment.gpsLon

    # Network config
    if package.deployment.backendAddr:
        network = ET.SubElement(root, "network")
        ET.SubElement(network, "backend_address").text = package.deployment.backendAddr

        if package.deployment.swdallowMasks:
            ET.SubElement(network, "swd_allow_masks").text = package.deployment.swdallowMasks
        if package.deployment.nativeallowMasks:
            ET.SubElement(network, "native_allow_masks").text = package.deployment.nativeallowMasks

    # ROI Configuration
    rois_element = ET.SubElement(root, "rois")
    rois_element.set("count", str(len(package.rois)))

    for i, roi in enumerate(package.rois):
        roi_element = ET.SubElement(rois_element, "roi")
        roi_element.set("id", roi.id or f"ROI-{i+1}")
        roi_element.set("index", str(i))

        # Points
        if roi.points and len(roi.points) >= 3:
            points_element = ET.SubElement(roi_element, "points")
            points_element.set("count", str(len(roi.points)))

            for j, point in enumerate(roi.points):
                point_element = ET.SubElement(points_element, "point")
                point_element.set("index", str(j))
                point_element.set("x", str(point.get('x', 0)))
                point_element.set("y", str(point.get('y', 0)))

        # Parameters
        params_element = ET.SubElement(roi_element, "parameters")
        ET.SubElement(params_element, "angle").text = str(getattr(roi, 'angle', 0))
        ET.SubElement(params_element, "zoom").text = str(getattr(roi, 'zoom', 1.0))
        ET.SubElement(params_element, "skew_h").text = str(getattr(roi, 'skewH', 0))
        ET.SubElement(params_element, "skew_v").text = str(getattr(roi, 'skewV', 0))
        ET.SubElement(params_element, "reflex_offset_h").text = str(getattr(roi, 'reflexOffsetH', 0))
        ET.SubElement(params_element, "reflex_offset_v").text = str(getattr(roi, 'reflexOffsetV', 0))

    # Image data (optional)
    if image_data:
        image_element = ET.SubElement(root, "reference_image")
        image_element.set("format", "base64")
        image_element.set("type", "jpeg")
        # Zapisz tylko header - pełny obraz byłby za duży
        if image_data.startswith('data:image'):
            header, data = image_data.split(',', 1)
            image_element.text = data[:1000] + "..." if len(data) > 1000 else data
        else:
            image_element.text = image_data[:1000] + "..." if len(image_data) > 1000 else image_data

    # Configuration files section
    config_files = ET.SubElement(root, "configuration_files")

    # INI config
    ini_config = ET.SubElement(config_files, "ini_config")
    ini_config.set("filename", f"{package.deployment.locationId}.ini")
    ini_content = build_roi_config_ini(package)
    ini_config.text = ini_content

    # Format XML with pretty printing
    rough_string = ET.tostring(root, encoding='unicode')
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ")

    # Remove empty lines
    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    return '\n'.join(lines)

# ===== INICJALIZACJA =====
app_start_time = time.time()

@app.on_event("startup")
async def startup_event():
    """Wykonuje inicjalizację przy starcie aplikacji"""
    global app_start_time
    app_start_time = time.time()
    logging.info("🎯 NCPyVisual Web Professional uruchomiona (ulepszona wersja z najlepszymi elementami)")

@app.on_event("shutdown")
async def shutdown_event():
    """Wykonuje cleanup przy wyłączaniu aplikacji"""
    logging.info("🛑 Zamykanie NCPyVisual Web Professional...")
    logging.info("✅ Aplikacja zamknięta")

# ===== ROUTES =====
@app.get("/", response_class=HTMLResponse)
async def root(req: Request):
    return templates.TemplateResponse("index.html", {"request": req})

@app.get("/health/")
async def health_check():
    """Endpoint sprawdzania stanu systemu z szczegółami NCShot"""
    try:
        # Test połączenia z NCShot
        ncshot_status = "unknown"
        ncshot_details = {}
        try:
            test_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=5)
            test_hc.request("GET", "/")
            test_resp = test_hc.getresponse()
            test_content = test_resp.read().decode('utf-8', 'ignore')
            test_hc.close()

            ncshot_status = "ok" if test_resp.status == 200 else f"error_{test_resp.status}"
            ncshot_details = {
                "http_status": test_resp.status,
                "response_length": len(test_content),
                "response_preview": test_content[:100] if test_content else None
            }
        except Exception as e:
            ncshot_status = f"unreachable: {str(e)}"
            ncshot_details = {"error": str(e)}

        config_status = {
            "vm_host": VM_HOST,
            "vm_user": VM_USER,
            "vm_pass_configured": bool(VM_PASS),
            "ncshot_host": NCSHOT_HOST,
            "ncshot_port": NCSHOT_PORT,
            "ncshot_status": ncshot_status,
            "ncshot_details": ncshot_details
        }

        return {
            "status": "healthy" if ncshot_status == "ok" else "degraded",
            "version": "3.2.0-ultimate-enhanced",
            "main_functionality": "NCShot Professional (ulepszona z najlepszymi elementami ze starszej wersji)",
            "config": config_status,
            "limits": {
                "max_image_size_mb": MAX_IMAGE_SIZE // (1024*1024),
                "min_image_size_bytes": MIN_IMAGE_SIZE,
                "min_plate_size_bytes": MIN_PLATE_SIZE,
                "max_plate_size_kb": MAX_PLATE_SIZE // 1024,
                "max_images_per_batch": 20
            },
            "professional_features": {
                "detailed_xml_parsing": True,
                "vehicle_recognition": True,
                "plate_variants": True,
                "professional_table": True,
                "enhanced_statistics": True,
                "modal_plate_view": True,
                "smart_plate_fetching": True,
                "multiple_fetch_strategies": True,
                "robust_error_handling": True,
                "advanced_xml_debugging": True,
                "enhanced_endpoint_testing": True,
                "xml_scene_export": True,
                "memory_management": True
            },
            "legacy_improvements": {
                "xml_structure_debugging": "Szczegółowe debugowanie struktury XML",
                "multiple_endpoint_testing": "Testowanie różnych endpointów tablic",
                "enhanced_parsing": "Ulepszony parser z obsługą wszystkich formatów",
                "better_logging": "Rozszerzone logowanie dla debugowania",
                "plate_validation": "Lepsza walidacja obrazów tablic",
                "enhanced_ini_generator": "Ulepszony generator INI zgodny z wzorcem",
                "immediate_token_release": "Natychmiastowe zwalnianie tokenów",
                "memory_optimization": "Wymuszone czyszczenie pamięci"
            },
            "logic_import": "OK",
            "models": "OK",
            "timestamp": datetime.now().isoformat(),
            "uptime": time.time() - app_start_time,
            "debugging": {
                "debug_plates_endpoint": "/debug-plates/",
                "debug_xml_endpoint": "/debug-xml/",
                "debug_ncshot_endpoint": "/debug-ncshot/",
                "health_endpoint": "/health/"
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/debug-plates/")
async def debug_plates():
    """Endpoint do debugowania problemów z tablicami"""
    return {
        "status": "debug_endpoint_active",
        "version": "professional-ultimate-enhanced",
        "ncshot_config": {
            "host": NCSHOT_HOST,
            "port": NCSHOT_PORT,
            "endpoint": f"http://{NCSHOT_HOST}:{NCSHOT_PORT}/vehicleplate"
        },
        "limits": {
            "max_plate_size_bytes": MAX_PLATE_SIZE,
            "min_plate_size_bytes": MIN_PLATE_SIZE,
            "max_image_size_bytes": MAX_IMAGE_SIZE,
            "min_image_size_bytes": MIN_IMAGE_SIZE
        },
        "professional_features": {
            "enhanced_xml_parsing": "process_ncshot_result_xml_enhanced",
            "detailed_plates_extraction": "extract_detailed_plates_from_xml",
            "plate_image_assignment": "assign_plate_images_to_data",
            "vehicle_data_parsing": True,
            "mmr_divergence_calculation": True,
            "smart_plate_fetching": "get_plates_from_ncshot_enhanced",
            "robust_plate_fetching": "test_plate_endpoints",
            "debug_xml_structure": "debug_xml_structure",
            "advanced_logging": True,
            "immediate_token_release": True,
            "memory_management": True
        },
        "legacy_improvements": {
            "from_older_version": [
                "debug_xml_structure() - szczegółowe debugowanie struktury XML",
                "test_plate_endpoints() - testowanie wszystkich możliwych endpointów",
                "process_ncshot_result_xml_enhanced() - lepszy parser XML",
                "get_plates_from_ncshot_enhanced() - ulepszone pobieranie tablic",
                "Lepsza obsługa błędów 404/500",
                "Rozszerzone logowanie na każdym etapie",
                "Natychmiastowe zwalnianie tokenów NCShot",
                "Wymuszone czyszczenie pamięci po każdym obrazie",
                "Circuit breaker przy błędach pamięci"
            ]
        },
        "debug_tips": [
            "Sprawdź logi serwera dla szczegółów błędów tablic",
            "Użyj debugPlates() w konsoli przeglądarki",
            "Sprawdź czy NCShot endpoint /vehicleplate działa",
            "Zweryfikuj czy XML zawiera dane tablic w elementach <exdata>",
            "Sprawdź czy tokeny są poprawnie generowane",
            "Sprawdź połączenie sieciowe z NCShot",
            "Sprawdź czy detailed_plates_with_images są generowane",
            "NOWE: Szczegółowe debugowanie struktury XML w logach",
            "NOWE: Testowanie wszystkich możliwych endpointów tablic",
            "NOWE: Lepsza walidacja z różnymi limitami dla tablic vs obrazów",
            "NOWE: Używa najlepszych elementów ze starszej wersji",
            "NOWE: Natychmiastowe zwalnianie tokenów zapobiega przeciekom pamięci",
            "NOWE: Circuit breaker przerywa przetwarzanie przy błędach 500"
        ],
        "timestamp": datetime.now().isoformat()
    }

@app.post("/ncshot/")
async def ncshot_endpoint(body: NcshotRequest):
    """🚀 GŁÓWNA FUNKCJONALNOŚĆ - Endpoint dla NCShot Professional z najlepszymi elementami"""
    logging.info("🚀 === URUCHAMIANIE GŁÓWNEJ FUNKCJONALNOŚCI NCSHOT PROFESSIONAL ===")
    logging.info(f"   📊 ROI: {len(body.package.rois)}")
    logging.info(f"   🖼ī¸ Obrazy: {len(body.image_files)}")

    try:
        if not body.image_files:
            raise HTTPException(status_code=400, detail="Wymagane są obrazy do przetworzenia.")

        if not body.package.deployment.locationId:
            raise HTTPException(status_code=400, detail="Wymagane jest ID lokalizacji.")

        # Sprawdź liczebność obrazów (zabezpieczenie przed przeciążeniem)
        if len(body.image_files) > 20:
            raise HTTPException(status_code=400, detail="Maksymalnie 20 obrazów na raz (zabezpieczenie pamięci)")

        # 🚀 GŁÓWNA FUNKCJONALNOŚĆ - UŻYWAMY ULEPSZONEJ WERSJI PROFESSIONAL
        results = start_ncshot_with_config_safe(body.package, body.image_files)

        # 🔧 ZABEZPIECZENIE: Upewnij się że wszystkie dane można serializować do JSON
        try:
            import json
            json.dumps(results)
        except (TypeError, ValueError) as e:
            logging.error(f"🔧 Błąd serializacji JSON, konwertuję: {e}")
            results = ensure_json_serializable(results)

        logging.info(f"✅ === NCSHOT PROFESSIONAL ZAKOŃCZONY POMYŚLNIE - {len(results)-1} wyników ===")
        return JSONResponse({"results": results, "success": True})

    except Exception as e:
        logging.error(f"⚠ī¸ Błąd krytyczny w głównej funkcjonalności NCShot Professional: {e}\n{traceback.format_exc()}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/import-from-device/")
async def import_from_device_endpoint(req: Request):
    logging.info("Endpoint /import-from-device/ został wywołany.")
    try:
        data = await req.json()
        ip = data.get("ip")
        pw = data.get("password")
        if not ip:
            raise HTTPException(status_code=400, detail="Brak IP terminala")
        config = get_device_config(ip, pw)
        logging.info("Pomyślnie zaimportowano konfigurację z urządzenia.")
        return config
    except Exception as e:
        logging.error(f"Błąd w /import-from-device/: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/fetch-device-images/")
async def fetch_device_images_endpoint(req: Request):
    logging.info("Endpoint /fetch-device-images/ został wywołany.")
    try:
        data = await req.json()
        ip = data.get("ip")
        pw = data.get("password")
        count = int(data.get("count", 10))
        if not ip:
            raise HTTPException(status_code=400, detail="Brak IP terminala")

        # Ogranicz liczbę obrazów (zabezpieczenie)
        if count > 50:
            count = 50
            logging.warning(f"⚠ī¸ Ograniczono liczbę obrazów do {count} (zabezpieczenie)")

        imgs = fetch_images_from_device(ip, pw, count)
        logging.info(f"Pomyślnie pobrano {len(imgs)} obrazów.")
        return JSONResponse({"images": imgs})
    except Exception as e:
        logging.error(f"Błąd w /fetch-device-images/: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-package/")
async def generate_package_endpoint(pkg: FullPackage):
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{pkg.deployment.locationId}.ini", build_roi_config_ini(pkg))
            readme = f"""# Pakiet konfiguracyjny dla {pkg.deployment.locationId}

Główna funkcjonalność: NCShot Professional (ulepszona wersja z najlepszymi elementami)
Wersja: 3.2.0-ultimate-enhanced

Limity:
- max {MAX_IMAGE_SIZE//1024//1024}MB na obraz
- {MIN_PLATE_SIZE}-{MAX_PLATE_SIZE//1024}KB na tablicę

Funkcje Professional:
- Szczegółowe parsowanie XML z exdata
- Rozpoznawanie pojazdów (marka, model, kolor)
- Warianty tablic z poziomami rozpoznania
- Profesjonalna tabela wyników
- Modal do powiększania tablic
- Rozszerzone statystyki
- NOWE: Ulepszone debugowanie XML
- NOWE: Testowanie wielu endpointów tablic
- NOWE: Najlepsze elementy ze starszej wersji
- NOWE: Eksport sceny XML z rozszerzoną konfiguracją INI
- NOWE: Natychmiastowe zwalnianie tokenów
- NOWE: Zarządzanie pamięcią z circuit breaker
"""
            z.writestr("README.txt", readme)
        ts = time.strftime("%Y%m%d-%H%M%S")
        name = f"ncpy_professional_ultimate_{pkg.deployment.locationId}_{ts}.zip"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="application/x-zip-compressed",
            headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania pakietu: {e}")

@app.post("/export-scene-xml/")
async def export_scene_xml(request: Request):
    """Eksportuje scenę do pliku XML"""
    try:
        data = await request.json()

        # Pobierz dane z requesta
        package_data = data.get('package')
        if not package_data:
            raise HTTPException(status_code=400, detail="Brak danych pakietu")

        # Utwórz obiekt FullPackage
        package = FullPackage(
            rois=[RoiData(**roi) for roi in package_data.get('rois', [])],
            deployment=DeploymentConfig(**package_data.get('deployment', {}))
        )

        if not package.deployment.locationId:
            raise HTTPException(status_code=400, detail="Wymagane ID lokalizacji")

        # Opcjonalny obraz referencyjny
        reference_image = data.get('reference_image', '')

        # Generuj XML
        xml_content = build_scene_xml(package, reference_image)

        # Przygotuj response jako download
        filename = f"{package.deployment.locationId}_scene.xml"

        return Response(
            content=xml_content,
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except Exception as e:
        logging.error(f"Błąd eksportu XML: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd eksportu: {str(e)}")

@app.post("/test-connection/")
async def test_connection(connection_data: dict):
    """Testuje połączenie z urządzeniem bez wykonywania operacji"""
    try:
        connection_type = connection_data.get("type", "vm")

        if connection_type == "vm":
            vm = connect_to_vm()
            stdin, stdout, stderr = vm.exec_command("echo 'test'", timeout=10)
            result = stdout.read().decode('utf-8').strip()
            vm.close()

            return {
                "status": "success",
                "message": "Połączenie z VM udane",
                "test_output": result
            }

        elif connection_type == "device":
            device_ip = connection_data.get("ip")
            device_pass = connection_data.get("password")

            if not device_ip:
                raise HTTPException(status_code=400, detail="Brak IP urządzenia")

            jump, dev = open_via_jump(device_ip, device_pass)

            stdin, stdout, stderr = dev.exec_command("echo 'test'", timeout=10)
            result = stdout.read().decode('utf-8').strip()

            dev.close()
            jump.close()

            return {
                "status": "success",
                "message": f"Połączenie z urządzeniem {device_ip} udane",
                "test_output": result
            }
        else:
            raise HTTPException(status_code=400, detail="Nieznany typ połączenia")

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Błąd testowania połączenia: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd połączenia: {e}")

@app.post("/debug-xml/")
async def debug_xml_endpoint(request: Request):
    """🔍 Endpoint do debugowania XML z NCShot - pokaże strukturę i wyniki parsowania"""
    try:
        data = await request.json()
        xml_content = data.get("xml_content", "")

        if not xml_content:
            raise HTTPException(status_code=400, detail="Brak xml_content w żądaniu")

        logging.info("🔍 === DEBUGOWANIE XML PRZEZ ENDPOINT ===")

        # Debuguj strukturę
        debug_xml_structure(xml_content)

        # Sparsuj wyniki
        parsed_results = process_ncshot_result_xml_enhanced(xml_content)
        detailed_plates = extract_detailed_plates_from_xml(xml_content)

        return {
            "status": "success",
            "parsed_results": parsed_results,
            "detailed_plates": detailed_plates,
            "statistics": {
                "total_plates": len(detailed_plates),
                "plates_with_text": len([r for r in detailed_plates if r.get("symbol")]),
                "vehicles": len(parsed_results.get("vehicles", [])),
                "processing_successful": parsed_results.get("processing_successful", False)
            },
            "message": f"Znaleziono {len(detailed_plates)} tablic i {len(parsed_results.get('vehicles', []))} pojazdów. Sprawdź logi dla szczegółów struktury XML."
        }

    except Exception as e:
        logging.error(f"Błąd debugowania XML: {e}")
        raise HTTPException(status_code=500, detail=f"Błąd parsowania XML: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
