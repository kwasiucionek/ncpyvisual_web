# app/logic.py - KOMPLETNY KOD PO ZMIANACH Z PEŁNĄ OBSŁUGĄ NCSHOT
import pandas as pd
import numpy as np
from io import StringIO
import xml.etree.ElementTree as ET
import json
import logging

def process_prn_file(file_content: str):
    """
    Przetwarza zawartość pliku PRN i zwraca dane gotowe do wygenerowania wykresu.
    """
    sio = StringIO(file_content)
    df = pd.read_csv(sio, sep='\t', skiprows=2)
    df.columns = ['Time', 'Value']
    time_data = df['Time'].tolist()
    value_data = df['Value'].tolist()
    average = np.mean(value_data)
    std_dev = np.std(value_data)
    return {
        "labels": time_data,
        "data": value_data,
        "stats": { "average": f"{average:.4f}", "std_dev": f"{std_dev:.4f}" }
    }

def process_ncshot_result_xml(xml_content: str):
    """
    Przetwarza zawartość XML z wynikiem NCShot - PEŁNA IMPLEMENTACJA
    Bazuje na formacie z sampleNCSHOTResult.xml i logice ze starej aplikacji.
    """
    try:
        root = ET.fromstring(xml_content)
        result = { 
            "plates": [], 
            "vehicles": [], 
            "timestamp": None, 
            "processing_parameters": {}, 
            "radar_data": {}, 
            "signature": None,
            "trace_data": {},
            "neural_net_data": {}
        }

        # Parsowanie timestamp
        timestamp_elem = root.find("timestamp")
        if timestamp_elem is not None:
            date_elem = timestamp_elem.find("date")
            time_elem = timestamp_elem.find("time")
            ms_elem = timestamp_elem.find("ms")
            if all(e is not None for e in [date_elem, time_elem, ms_elem]):
                result["timestamp"] = {
                    "date": date_elem.text, 
                    "time": time_elem.text, 
                    "ms": ms_elem.text,
                    "formatted": f"{date_elem.text} {time_elem.text}.{ms_elem.text}"
                }

        # Parsowanie exdata - główne dane
        exdata_elem = root.find("exdata")
        if exdata_elem is not None:
            for data_elem in exdata_elem.findall("data"):
                data_name = data_elem.get("name", "")
                data_source = data_elem.get("source", "")
                data_values = {}
                
                # Zbieranie wszystkich wartości
                for v in data_elem.findall("value"):
                    value_name = v.get("name", "")
                    value_text = v.text or ""
                    data_values[value_name] = value_text

                # Przetwarzanie różnych typów danych
                if "plate" in data_name and "trace" not in data_name and data_values:
                    # Przetwarzanie danych tablic rejestracyjnych
                    confidence = 0.0
                    try: 
                        level = data_values.get("level", "0")
                        confidence = float(level) / 100.0
                    except (ValueError, TypeError): 
                        pass
                    
                    plate_data = {
                        "text": data_values.get("symbol", ""),
                        "country": data_values.get("country", ""),
                        "confidence": confidence,
                        "level": data_values.get("level", "0"),
                        "type": data_values.get("type", ""),
                        "position": data_values.get("position", ""),
                        "prefix": data_values.get("prefix", ""),
                        "doubleline": data_values.get("doubleline", "0"),
                        "source": data_source,
                        "data_name": data_name
                    }
                    result["plates"].append(plate_data)

                elif data_name == "vehicle" and data_values:
                    # Przetwarzanie danych pojazdu
                    confidence = 0.8
                    try:
                        divergence = float(data_values.get("mmrpatterndivergence", "0"))
                        if divergence > 0:
                            confidence = max(0.1, 1.0 / (1.0 + divergence))
                    except (ValueError, TypeError): 
                        pass
                    
                    vehicle_data = {
                        "make": data_values.get("manufacturer", ""),
                        "model": data_values.get("model", ""),
                        "type": data_values.get("type", ""),
                        "color": data_values.get("color", ""),
                        "confidence": confidence,
                        "direction": data_values.get("direction", ""),
                        "speed": data_values.get("speed", "0.0"),
                        "estimated_speed": data_values.get("estimatedspeed", "0.0"),
                        "acceleration": data_values.get("acceleration", "0.0"),
                        "mmr_pattern_index": data_values.get("mmrpatternindex", ""),
                        "mmr_pattern_divergence": data_values.get("mmrpatterndivergence", ""),
                        "mmr_roi_box": data_values.get("mmrroibox", ""),
                        "duplicate": data_values.get("duplicate", "0"),
                        "pixel_speed": data_values.get("pixelspeed", "0.0")
                    }
                    result["vehicles"].append(vehicle_data)

                elif data_name == "neuralnet" and data_source == "camera":
                    # Przetwarzanie danych sieci neuronowej
                    if "signature" in data_values:
                        result["signature"] = data_values["signature"]
                    result["neural_net_data"] = data_values

                elif data_name == "parameters" and data_source == "camera":
                    # Parametry przetwarzania
                    result["processing_parameters"] = data_values

                elif "trace" in data_name:
                    # Dane śledzenia (platetrace)
                    result["trace_data"][data_name] = data_values

                elif data_name == "zur" or "radar" in data_source:
                    # Dane z radaru
                    radar_data = {
                        "speed": data_values.get("speed", "0.0"),
                        "direction": data_values.get("direction", "1"),
                        "source": data_source
                    }
                    result["radar_data"] = radar_data

        # Generowanie podsumowania
        best_plate_confidence = 0.0
        if result["plates"]:
            best_plate_confidence = max([p["confidence"] for p in result["plates"]], default=0.0)
        
        best_vehicle_confidence = 0.0
        if result["vehicles"]:
            best_vehicle_confidence = max([v["confidence"] for v in result["vehicles"]], default=0.0)

        result["summary"] = {
            "plates_detected": len(result["plates"]),
            "vehicles_detected": len(result["vehicles"]),
            "best_plate_confidence": best_plate_confidence,
            "best_vehicle_confidence": best_vehicle_confidence,
            "processing_successful": bool(result["plates"] or result["vehicles"]),
            "has_signature": bool(result["signature"]),
            "has_radar_data": bool(result["radar_data"]),
            "timestamp_available": bool(result["timestamp"])
        }
        
        # Dodatkowe statystyki dla lepszego raportu
        if result["plates"]:
            countries = [p["country"] for p in result["plates"] if p["country"]]
            result["summary"]["countries_detected"] = list(set(countries))
            
        if result["vehicles"]:
            vehicle_types = [v["type"] for v in result["vehicles"] if v["type"]]
            result["summary"]["vehicle_types"] = list(set(vehicle_types))

        return result

    except ET.ParseError as e:
        logging.error(f"Błąd parsowania XML: {e}")
        return {
            "error": f"Błąd parsowania XML: {str(e)}", 
            "raw_content": xml_content[:1000] + "..." if len(xml_content) > 1000 else xml_content,
            "summary": {"processing_successful": False, "error_type": "xml_parse_error"}
        }
    except Exception as e:
        logging.error(f"Błąd przetwarzania danych XML: {e}")
        return {
            "error": f"Błąd przetwarzania danych XML: {str(e)}", 
            "raw_content": xml_content[:1000] + "..." if len(xml_content) > 1000 else xml_content,
            "summary": {"processing_successful": False, "error_type": "processing_error"}
        }

def process_ncsim_result(output: str):
    """
    Przetwarza wynik z ncsim (format tekstowy), bazując na logice starej aplikacji.
    """
    result = {
        "plates": [], 
        "vehicles": [], 
        "processing_successful": False,
        "ncsim_output": output, 
        "recog_strong": None, 
        "recog_weak": None,
        "processing_time": None
    }

    try:
        lines = output.split("\n")
        for line in lines:
            line_lower = line.strip().lower()
            line_original = line.strip()
            
            if "recog-strong" in line_lower:
                try: 
                    value_part = line_original.split(":")[1].replace("%", "").strip()
                    result["recog_strong"] = float(value_part)
                except (IndexError, ValueError): 
                    pass
                    
            if "recog-weak" in line_lower:
                try: 
                    value_part = line_original.split(":")[1].replace("%", "").strip()
                    result["recog_weak"] = float(value_part)
                except (IndexError, ValueError): 
                    pass
                    
            if "time" in line_lower and ("sec" in line_lower or "ms" in line_lower):
                result["processing_time"] = line_original.strip()

        # Określenie czy przetwarzanie się powiodło
        if result["recog_strong"] is not None or result["recog_weak"] is not None:
            result["processing_successful"] = True
            
            # Tworzenie symbolicznego wyniku tablicy na podstawie procentów
            if result["recog_strong"] and result["recog_strong"] > 30:
                result["plates"].append({
                    "text": f"SYMULACJA OK ({result['recog_strong']:.1f}%)",
                    "confidence": result["recog_strong"] / 100.0,
                    "source": "ncsim",
                    "type": "simulation_result"
                })

        # Podsumowanie wyników
        result["summary"] = {
            "plates_detected": len(result["plates"]),
            "processing_successful": result["processing_successful"],
            "recog_strong_percent": result["recog_strong"],
            "recog_weak_percent": result["recog_weak"],
            "has_timing_info": bool(result["processing_time"])
        }

    except Exception as e:
        result["error"] = f"Błąd parsowania ncsim: {e}"
        result["summary"] = {
            "processing_successful": False, 
            "error": str(e),
            "error_type": "ncsim_parse_error"
        }

    return result
