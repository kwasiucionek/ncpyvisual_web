# app/logic.py - KOMPLETNY KOD PO ZMIANACH
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
    Przetwarza zawartość XML z wynikiem NCShot (stara architektura)
    Udoskonalona funkcja - zgodna z formatem z sampleNCSHOTResult.xml i odporna na błędy.
    """
    try:
        root = ET.fromstring(xml_content)
        result = { "plates": [], "vehicles": [], "timestamp": None, "processing_parameters": {}, "radar_data": {}, "signature": None }

        timestamp_elem = root.find("timestamp")
        if timestamp_elem is not None:
            date_elem = timestamp_elem.find("date")
            time_elem = timestamp_elem.find("time")
            ms_elem = timestamp_elem.find("ms")
            if all(e is not None for e in [date_elem, time_elem, ms_elem]):
                result["timestamp"] = {"date": date_elem.text, "time": time_elem.text, "ms": ms_elem.text}

        exdata_elem = root.find("exdata")
        if exdata_elem is not None:
            for data_elem in exdata_elem.findall("data"):
                data_name = data_elem.get("name", "")
                data_source = data_elem.get("source", "")
                data_values = {v.get("name", ""): v.text or "" for v in data_elem.findall("value")}

                if "plate" in data_name and "trace" not in data_name and data_values:
                    confidence = 0.0
                    try: confidence = float(data_values.get("level", "0")) / 100.0
                    except (ValueError, TypeError): pass
                    result["plates"].append({
                        "text": data_values.get("symbol", ""), "country": data_values.get("country", ""),
                        "confidence": confidence, "type": data_values.get("type", ""), "position": data_values.get("position", "")
                    })

                elif data_name == "vehicle" and data_values:
                    confidence = 0.8
                    try:
                        divergence = float(data_values.get("mmrpatterndivergence", "0"))
                        confidence = max(0.1, 1.0 / (1.0 + divergence))
                    except (ValueError, TypeError): pass
                    result["vehicles"].append({
                        "make": data_values.get("manufacturer", ""), "model": data_values.get("model", ""),
                        "type": data_values.get("type", ""), "color": data_values.get("color", ""), "confidence": confidence
                    })

                elif data_name == "neuralnet" and "signature" in data_values:
                    result["signature"] = data_values["signature"]
                elif data_name == "parameters":
                    result["processing_parameters"] = data_values
                elif data_name == "zur" or "radar" in data_source:
                    result["radar_data"] = data_values

        result["summary"] = {
            "plates_detected": len(result["plates"]),
            "vehicles_detected": len(result["vehicles"]),
            "best_plate_confidence": max([p["confidence"] for p in result["plates"]], default=0.0),
            "processing_successful": bool(result["plates"] or result["vehicles"])
        }
        return result

    except ET.ParseError as e:
        logging.error(f"Błąd parsowania XML: {e}")
        return {"error": f"Błąd parsowania XML: {str(e)}", "raw_content": xml_content}
    except Exception as e:
        logging.error(f"Błąd przetwarzania danych XML: {e}")
        return {"error": f"Błąd przetwarzania danych XML: {str(e)}", "raw_content": xml_content}

def process_ncsim_result(output: str):
    """
    Przetwarza wynik z ncsim (format tekstowy), bazując na logice starej aplikacji.
    """
    result = {
        "plates": [], "vehicles": [], "processing_successful": False,
        "ncsim_output": output, "recog_strong": None, "recog_weak": None,
        "processing_time": None
    }

    try:
        lines = output.split("\n")
        for line in lines:
            line = line.strip().lower()
            if "recog-strong" in line:
                try: result["recog_strong"] = float(line.split(":")[1].replace("%", "").strip())
                except: pass
            if "recog-weak" in line:
                try: result["recog_weak"] = float(line.split(":")[1].replace("%", "").strip())
                except: pass
            if "time" in line and ("sec" in line or "ms" in line):
                result["processing_time"] = line.strip()

        if result["recog_strong"] is not None or result["recog_weak"] is not None:
            result["processing_successful"] = True
            if result["recog_strong"] and result["recog_strong"] > 30:
                result["plates"].append({
                    "text": f"SYMULACJA OK ({result['recog_strong']}%)",
                    "confidence": result["recog_strong"] / 100.0,
                    "source": "ncsim"
                })

        result["summary"] = {
            "plates_detected": len(result["plates"]),
            "processing_successful": result["processing_successful"],
            "recog_strong_percent": result["recog_strong"],
            "recog_weak_percent": result["recog_weak"],
        }

    except Exception as e:
        result["error"] = f"Błąd parsowania ncsim: {e}"
        result["summary"] = {"processing_successful": False, "error": str(e)}

    return result
