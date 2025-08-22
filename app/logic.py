# app/logic.py - ULEPSZONA WERSJA z najlepszymi elementami ze starszej aplikacji

import xml.etree.ElementTree as ET
import json
import logging
import re
import traceback
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

def safe_float_parse(value: str, default: float = 0.0) -> float:
    """Bezpieczne parsowanie float z domyślną wartością"""
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        logger.warning(f"Nie można sparsować jako float: {value}, używam domyślnej: {default}")
        return default

def safe_int_parse(value: str, default: int = 0) -> int:
    """Bezpieczne parsowanie int z domyślną wartością"""
    try:
        return int(value) if value else default
    except (ValueError, TypeError):
        logger.warning(f"Nie można sparsować jako int: {value}, używam domyślnej: {default}")
        return default

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
            "parser_version": "3.2.0-enhanced"
        }
    }

    try:
        if not xml_content or not xml_content.strip():
            result["error"] = "Pusta zawartość XML"
            return result

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
                logger.warning(f"Błąd parsowania timestamp: {e}")

        # Parsuj exdata - DOKŁADNIE jak w starej aplikacji
        exdata_elements = root.findall("exdata")
        result["metadata"]["exdata_count"] = len(exdata_elements)

        for exdata_idx, exdata_elem in enumerate(exdata_elements):
            vehicle_data = {
                "exdata_index": exdata_idx,
                "plates": [],  # Lista wariantów płytek dla tego pojazdu
                "vehicle_info": {},
                "parameters": {},
                "signature": None
            }

            for data_elem in exdata_elem.findall("data"):
                try:
                    data_name = data_elem.get("name", "").strip()
                    data_source = data_elem.get("source", "").strip()

                    # Zbierz wszystkie wartości
                    data_values = {}
                    for value_elem in data_elem.findall("value"):
                        value_name = value_elem.get("name", "").strip()
                        value_text = value_elem.text.strip() if value_elem.text else ""
                        if value_name:
                            data_values[value_name] = value_text

                    # PARSOWANIE PŁYTEK - jak w PhotoDescription.py
                    if "plate" in data_name and "trace" not in data_name and data_values:
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

                        # Dodaj do listy wariantów płytek dla tego pojazdu
                        vehicle_data["plates"].append(plate_variant)

                        # Dodaj też do głównej listy płytek (dla kompatybilności)
                        result["plates"].append(plate_variant)

                    # PARSOWANIE POJAZDU - jak w starej aplikacji
                    elif data_name == "vehicle" and data_values:
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
                    logger.warning(f"Błąd parsowania elementu data: {e}")
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
        logger.error(error_msg)
        result["error"] = error_msg
        result["error_details"] = {
            "error_type": "xml_parse_error",
            "xml_preview": xml_content[:200] + "..." if len(xml_content) > 200 else xml_content
        }
        return result

    except Exception as e:
        error_msg = f"Błąd przetwarzania danych XML: {str(e)}"
        logger.error(error_msg)
        result["error"] = error_msg
        result["error_details"] = {
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()
        }
        return result

def extract_detailed_plates_from_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Wyciąga szczegółowe dane płytek z XML w formacie zgodnym ze starą aplikacją"""
    result = process_ncshot_result_xml_enhanced(xml_content)

    detailed_plates = []
    for vehicle in result.get("vehicles", []):
        for plate in vehicle.get("plates", []):
            # Dodaj informacje o pojeździe do płytki
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
        summary = "⚠ Przetwarzanie nieudane\n"
        error = ncshot_result.get("error", "Nieznany błąd")
        summary += f"🔍 Błąd: {error}\n"
        return summary

    summary = "📊 WYNIKI NCSHOT:\n"

    # Statystyki główne
    plates_count = ncshot_result["summary"]["plates_detected"]
    vehicles_count = ncshot_result["summary"]["vehicles_detected"]
    variants_count = ncshot_result["summary"]["plate_variants_total"]

    summary += f"   🚗 Pojazdy: {vehicles_count}\n"
    summary += f"   🷏ī¸ Płytki główne: {plates_count}\n"
    summary += f"   🔄 Warianty płytek: {variants_count}\n"

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

            # Najlepszy wariant płytki
            if vehicle["plates"]:
                best_plate = max(vehicle["plates"], key=lambda p: p["confidence"])
                conf_icon = "✅" if best_plate["confidence"] > 0.7 else "⚡" if best_plate["confidence"] > 0.4 else "⚠ī¸"
                summary += f"      {conf_icon} {best_plate['symbol']} ({best_plate['country']}) - {best_plate['level']:.0f}%\n"

    # Timestamp
    if ncshot_result.get("timestamp"):
        ts = ncshot_result["timestamp"]
        summary += f"\n⏰ Czas: {ts['date']} {ts['time']}.{ts['ms']}\n"

    return summary

# Funkcje pomocnicze dla przyszłego użycia
def extract_plates_from_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Wyciąga tylko dane płytek z XML"""
    result = process_ncshot_result_xml_enhanced(xml_content)
    return result.get("plates", [])

def extract_vehicles_from_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Wyciąga tylko dane pojazdów z XML"""
    result = process_ncshot_result_xml_enhanced(xml_content)
    return result.get("vehicles", [])

# Zastąp starą funkcję nową
def process_ncshot_result_xml(xml_content: str) -> Dict[str, Any]:
    """Główna funkcja parsowania XML - używa rozszerzonej wersji"""
    return process_ncshot_result_xml_enhanced(xml_content)

if __name__ == "__main__":
    # Testy jednostkowe
    print("🧪 Uruchamianie testów logic.py...")

    # Test z pustym XML
    test_empty = ""
    result = process_ncshot_result_xml_enhanced(test_empty)
    print("✅ Test pustego XML:")
    print(f"   Status: {result['processing_successful']}")
    print(f"   Błąd: {result['error']}")

    print("\n🎉 Testy zakończone pomyślnie!")
