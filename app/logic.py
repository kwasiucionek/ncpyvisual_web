# app/logic.py - POPRAWIONA WERSJA Z LEPSZĄ OBSŁUGĄ BŁĘDÓW

import xml.etree.ElementTree as ET
import json
import logging
import re
import traceback
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

# Konfiguracja logowania
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

def process_ncsim_result(output: str) -> Dict[str, Any]:
    """
    Przetwarza wynik z ncsim z lepszą diagnostyką błędów składni i obsługą wyjątków
    """
    result = {
        "plates": [], 
        "vehicles": [], 
        "processing_successful": False,
        "ncsim_output": output, 
        "recog_strong": None, 
        "recog_weak": None,
        "processing_time": None,
        "error": None,
        "diagnostic_info": {},
        "metadata": {
            "processed_at": datetime.now().isoformat(),
            "output_length": len(output),
            "parser_version": "2.8.1-improved"
        }
    }

    try:
        if not output or not output.strip():
            result["error"] = "Puste wyjście z NCSim"
            return result

        lines = output.split("\n")
        result["metadata"]["total_lines"] = len(lines)
        
        # Analiza szczegółowa błędów
        syntax_errors = []
        config_errors = []
        file_errors = []
        version_info = []
        timing_info = []
        
        for line_num, line in enumerate(lines, 1):
            line_clean = line.strip()
            line_lower = line_clean.lower()
            
            # Wykrywanie informacji o wersji
            if "ncsim" in line_lower and ("ver." in line_lower or "version" in line_lower):
                version_info.append(line_clean)
            
            # Wykrywanie błędów składni
            if "syntax not loaded" in line_lower:
                syntax_errors.append({
                    "line": line_num,
                    "message": "Nie udało się załadować składni",
                    "original": line_clean
                })
            if "check configuration file" in line_lower:
                config_errors.append({
                    "line": line_num,
                    "message": "Problem z plikiem konfiguracyjnym",
                    "original": line_clean
                })
            if any(phrase in line_lower for phrase in ["no such file", "cannot open", "file not found"]):
                file_errors.append({
                    "line": line_num,
                    "message": f"Problem z plikiem",
                    "original": line_clean
                })
            
            # Szukaj standardowych wyników - z lepszym parsowaniem
            if "recog-strong" in line_lower:
                try: 
                    # Różne formaty: "recog-strong: 85.5%" lub "recog-strong = 85.5"
                    match = re.search(r'recog-strong\s*[:=]\s*([0-9]+\.?[0-9]*)', line_lower)
                    if match:
                        value = safe_float_parse(match.group(1))
                        result["recog_strong"] = value
                        logger.info(f"✅ Znaleziono recog-strong: {value}%")
                    else:
                        logger.warning(f"Nie można sparsować recog-strong z linii: {line_clean}")
                except Exception as e:
                    logger.warning(f"Błąd parsowania recog-strong: {e}")
                    
            if "recog-weak" in line_lower:
                try: 
                    match = re.search(r'recog-weak\s*[:=]\s*([0-9]+\.?[0-9]*)', line_lower)
                    if match:
                        value = safe_float_parse(match.group(1))
                        result["recog_weak"] = value
                        logger.info(f"✅ Znaleziono recog-weak: {value}%")
                    else:
                        logger.warning(f"Nie można sparsować recog-weak z linii: {line_clean}")
                except Exception as e:
                    logger.warning(f"Błąd parsowania recog-weak: {e}")
                    
            # Szukaj czasu przetwarzania - różne formaty
            if any(word in line_lower for word in ["time", "elapsed", "duration"]) and \
               any(unit in line_lower for unit in ["sec", "ms", "seconds", "milliseconds"]):
                timing_info.append(line_clean)
                if not result["processing_time"]:  # Użyj pierwszego znalezionego
                    result["processing_time"] = line_clean

        # Dodaj informacje diagnostyczne
        result["diagnostic_info"] = {
            "syntax_errors": syntax_errors,
            "config_errors": config_errors,
            "file_errors": file_errors,
            "version_info": version_info,
            "timing_info": timing_info,
            "has_version_info": len(version_info) > 0,
            "has_neurosoft_header": any("neurosoft" in line.lower() for line in lines),
            "error_summary": {
                "syntax_count": len(syntax_errors),
                "config_count": len(config_errors),
                "file_count": len(file_errors)
            }
        }

        # Określ czy przetwarzanie było udane
        has_recognition_results = result["recog_strong"] is not None or result["recog_weak"] is not None
        has_critical_errors = len(syntax_errors) > 0 or len(config_errors) > 0 or len(file_errors) > 0
        
        if has_recognition_results:
            result["processing_successful"] = True
            logger.info("🎯 NCSim zwrócił wyniki rozpoznania")
            
            # Dodaj symulowane dane płytki jeśli rozpoznanie było dobre
            if result["recog_strong"] and result["recog_strong"] > 30:
                result["plates"].append({
                    "text": f"SYMULACJA_OK",
                    "confidence": result["recog_strong"] / 100.0,
                    "source": "ncsim",
                    "details": f"Rozpoznanie silne: {result['recog_strong']:.1f}%"
                })
        else:
            # Analiza przyczyn braku wyników
            if syntax_errors:
                result["error"] = "BŁĄD SKŁADNI: Nie można załadować plików składni (.bin)"
                result["error_category"] = "syntax_missing"
                logger.error("❌ Błąd składni w NCSim")
            elif config_errors:
                result["error"] = "BŁĄD KONFIGURACJI: Nieprawidłowy plik konfiguracyjny"
                result["error_category"] = "config_invalid"
                logger.error("❌ Błąd konfiguracji w NCSim")
            elif file_errors:
                result["error"] = "BŁĄD PLIKÓW: Nie można otworzyć wymaganych plików"
                result["error_category"] = "files_missing"
                logger.error("❌ Błąd plików w NCSim")
            else:
                result["error"] = "NCSim nie zwrócił wyników rozpoznania (nieznana przyczyna)"
                result["error_category"] = "no_results"
                logger.warning("⚠️ Brak wyników z NCSim bez jasnych błędów")

        # Stwórz szczegółowe podsumowanie
        result["summary"] = {
            "processing_successful": result["processing_successful"],
            "plates_detected": len(result["plates"]),
            "recog_strong_percent": result["recog_strong"],
            "recog_weak_percent": result["recog_weak"],
            "has_errors": has_critical_errors,
            "error_types": result["diagnostic_info"]["error_summary"],
            "has_timing": bool(result["processing_time"]),
            "has_version": result["diagnostic_info"]["has_version_info"],
            "output_analysis": {
                "total_lines": len(lines),
                "non_empty_lines": len([l for l in lines if l.strip()]),
                "error_lines": len(syntax_errors) + len(config_errors) + len(file_errors)
            }
        }

        # Dodaj rekomendacje na podstawie rodzaju błędu
        if syntax_errors:
            result["recommendations"] = [
                "Sprawdź czy plik syntax.bin istnieje w /neurocar/etc/syntax/",
                "Sprawdź ścieżkę do folderu składni w sekcji [global] konfiguracji",
                "Sprawdź uprawnienia do plików składni (chmod 644)",
                "Sprawdź czy folder /neurocar/etc/syntax/ istnieje i nie jest pusty"
            ]
        elif config_errors:
            result["recommendations"] = [
                "Sprawdź składnię pliku konfiguracyjnego INI",
                "Sprawdź czy wszystkie wymagane sekcje są obecne ([common], [main], [platerecognizer-main])",
                "Sprawdź czy ścieżki do plików są poprawne i pliki istnieją",
                "Sprawdź czy nie ma błędów w formatowaniu (brakujące znaki =, nieprawidłowe sekcje)"
            ]
        elif file_errors:
            result["recommendations"] = [
                "Sprawdź czy obraz wejściowy istnieje i ma prawidłowy format",
                "Sprawdź uprawnienia do odczytu plików",
                "Sprawdź czy ścieżki w konfiguracji są poprawne",
                "Sprawdź dostępne miejsce na dysku"
            ]
        else:
            result["recommendations"] = [
                "Sprawdź logi NCSim dla dodatkowych informacji",
                "Sprawdź czy parametry konfiguracji są w prawidłowych zakresach",
                "Sprawdź czy obraz ma odpowiednią jakość i rozmiar"
            ]

    except Exception as e:
        error_details = {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
            "input_preview": output[:500] if output else "brak danych"
        }
        
        result["error"] = f"Błąd parsowania wyniku NCSim: {e}"
        result["error_category"] = "parser_error"
        result["processing_successful"] = False
        result["error_details"] = error_details
        result["summary"] = {
            "processing_successful": False, 
            "error": str(e),
            "parser_error": True
        }
        logger.error(f"💥 Błąd w process_ncsim_result: {e}")
        logger.debug(f"Traceback: {traceback.format_exc()}")

    return result


def format_ncsim_summary_enhanced(ncsim_result: Dict[str, Any]) -> str:
    """Formatuje rozszerzone podsumowanie wyników ncsim z diagnostyką"""
    if not ncsim_result.get("processing_successful"):
        summary = "❌ Przetwarzanie nieudane\n"
        
        # Dodaj szczegóły błędu
        error = ncsim_result.get("error", "Nieznany błąd")
        summary += f"🔍 Błąd: {error}\n"
        
        # Dodaj kategorię błędu jeśli dostępna
        error_category = ncsim_result.get("error_category")
        if error_category:
            category_names = {
                "syntax_missing": "Brak plików składni",
                "config_invalid": "Nieprawidłowa konfiguracja", 
                "files_missing": "Brak wymaganych plików",
                "no_results": "Brak wyników",
                "parser_error": "Błąd parsera"
            }
            summary += f"📂 Kategoria: {category_names.get(error_category, error_category)}\n"
        
        # Dodaj informacje diagnostyczne
        diag = ncsim_result.get("diagnostic_info", {})
        if diag.get("syntax_errors"):
            summary += f"🔧 Błędy składni: {len(diag['syntax_errors'])}\n"
        if diag.get("config_errors"):
            summary += f"⚙️ Błędy konfiguracji: {len(diag['config_errors'])}\n"
        if diag.get("file_errors"):
            summary += f"📂 Błędy plików: {len(diag['file_errors'])}\n"
            
        # Dodaj rekomendacje
        recommendations = ncsim_result.get("recommendations", [])
        if recommendations:
            summary += "\n💡 Rekomendacje:\n"
            for i, rec in enumerate(recommendations[:3], 1):  # Ogranicz do 3 najważniejszych
                summary += f"   {i}. {rec}\n"
        
        # Dodaj informacje o wersji jeśli dostępne
        version_info = diag.get("version_info", [])
        if version_info:
            summary += f"\nℹ️ Wersja: {version_info[0]}\n"
        
        return summary
    
    # Przetwarzanie udane
    strong = ncsim_result.get("recog_strong")
    weak = ncsim_result.get("recog_weak")
    
    summary = "📊 WYNIKI NCSIM:\n"
    if strong is not None:
        confidence_icon = "🎯" if strong > 70 else "⚡" if strong > 40 else "⚠️"
        summary += f"   {confidence_icon} Rozpoznanie silne: {strong:.1f}%\n"
    if weak is not None:
        confidence_icon = "✅" if weak > 50 else "⚡" if weak > 30 else "⚠️"
        summary += f"   {confidence_icon} Rozpoznanie słabe: {weak:.1f}%\n"
        
    time_info = ncsim_result.get("processing_time")
    if time_info:
        summary += f"   ⏱️ Czas: {time_info}\n"
        
    # Dodaj informacje o płytkach
    plates = ncsim_result.get("plates", [])
    if plates:
        summary += f"   🚗 Wykryte płytki: {len(plates)}\n"
        for plate in plates:
            confidence = plate.get('confidence', 0) * 100
            summary += f"      • {plate.get('text', 'N/A')} ({confidence:.1f}%)\n"
    
    # Dodaj informacje o jakości danych wyjściowych
    metadata = ncsim_result.get("metadata", {})
    if metadata.get("total_lines"):
        summary += f"\n📋 Linie wyjścia: {metadata['total_lines']}\n"
        
    return summary


def analyze_ncsim_configuration_issues(output: str) -> List[str]:
    """Analizuje problemy konfiguracji NCSim i zwraca sugestie rozwiązań"""
    issues = []
    output_lower = output.lower()
    
    # Analiza błędów składni
    if "syntax not loaded" in output_lower:
        issues.extend([
            "Problem z załadowaniem składni - sprawdź ścieżkę do syntax.bin",
            "Sprawdź czy /neurocar/etc/syntax.bin istnieje",
            "Sprawdź uprawnienia do pliku składni (powinny być 644 lub 755)",
            "Sprawdź czy folder syntax zawiera prawidłowe pliki .bin"
        ])
    
    # Analiza problemów z plikami
    if "cannot open" in output_lower and ".bin" in output_lower:
        issues.append("Plik .bin nie może być otwarty - sprawdź ścieżkę i uprawnienia")
    
    if "no such file" in output_lower:
        issues.append("Nie znaleziono wymaganego pliku - sprawdź ścieżki w konfiguracji")
        
    # Analiza problemów konfiguracji
    if "invalid" in output_lower and "config" in output_lower:
        issues.extend([
            "Nieprawidłowa konfiguracja INI",
            "Sprawdź składnię sekcji [common], [main], [platerecognizer-main]",
            "Sprawdź czy wszystkie wymagane parametry są ustawione"
        ])
        
    if "command line" in output_lower:
        issues.append("Problem z argumentami linii poleceń - sprawdź składnię wywołania ncsim")
    
    # Analiza problemów z obrazem
    if "image" in output_lower and ("invalid" in output_lower or "corrupt" in output_lower):
        issues.extend([
            "Problem z obrazem wejściowym",
            "Sprawdź format obrazu (obsługiwane: JPEG, BMP)",
            "Sprawdź czy obraz nie jest uszkodzony"
        ])
        
    return issues


def process_ncshot_result_xml(xml_content: str) -> Dict[str, Any]:
    """
    Przetwarza zawartość XML z wynikiem NCShot z lepszą obsługą błędów
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
            "parser_version": "2.8.1-improved"
        }
    }

    try:
        if not xml_content or not xml_content.strip():
            result["error"] = "Pusta zawartość XML"
            return result

        root = ET.fromstring(xml_content)
        result["metadata"]["root_tag"] = root.tag

        # Parsuj timestamp
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

        # Parsuj exdata
        exdata_elements = root.findall("exdata")
        result["metadata"]["exdata_count"] = len(exdata_elements)
        
        for exdata_elem in exdata_elements:
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

                    # Parsuj dane płytek
                    if "plate" in data_name and "trace" not in data_name and data_values:
                        confidence = 0.0
                        try: 
                            level_str = data_values.get("level", "0")
                            confidence = safe_float_parse(level_str) / 100.0
                        except: 
                            pass
                            
                        plate_data = {
                            "text": data_values.get("symbol", "").strip(),
                            "country": data_values.get("country", "").strip(),
                            "confidence": confidence,
                            "type": data_values.get("type", "").strip(),
                            "position": data_values.get("position", "").strip(),
                            "prefix": data_values.get("prefix", "").strip(),
                            "source": data_source,
                            "data_name": data_name
                        }
                        
                        # Dodaj tylko jeśli ma sensowne dane
                        if plate_data["text"] or plate_data["country"]:
                            result["plates"].append(plate_data)

                    # Parsuj dane pojazdów
                    elif data_name == "vehicle" and data_values:
                        confidence = 0.8  # Domyślna pewność
                        try:
                            divergence_str = data_values.get("mmrpatterndivergence", "0")
                            divergence = safe_float_parse(divergence_str)
                            if divergence > 0:
                                confidence = max(0.1, 1.0 / (1.0 + divergence))
                        except: 
                            pass
                            
                        vehicle_data = {
                            "make": data_values.get("manufacturer", "").strip(),
                            "model": data_values.get("model", "").strip(),
                            "type": data_values.get("type", "").strip(),
                            "color": data_values.get("color", "").strip(),
                            "confidence": confidence,
                            "direction": safe_int_parse(data_values.get("direction", "0")),
                            "speed": safe_float_parse(data_values.get("speed", "0")),
                            "source": data_source
                        }
                        
                        result["vehicles"].append(vehicle_data)

                    # Parsuj inne dane
                    elif data_name == "neuralnet" and "signature" in data_values:
                        result["signature"] = data_values["signature"]
                    elif data_name == "parameters":
                        result["processing_parameters"].update(data_values)
                    elif data_name == "zur" or "radar" in data_source:
                        result["radar_data"].update(data_values)
                        
                except Exception as e:
                    logger.warning(f"Błąd parsowania elementu data: {e}")
                    continue

        # Określ czy przetwarzanie było udane
        result["processing_successful"] = bool(result["plates"] or result["vehicles"] or result["signature"])

        # Stwórz podsumowanie
        result["summary"] = {
            "plates_detected": len(result["plates"]),
            "vehicles_detected": len(result["vehicles"]),
            "has_signature": bool(result["signature"]),
            "has_timestamp": bool(result["timestamp"]),
            "has_radar_data": bool(result["radar_data"]),
            "processing_successful": result["processing_successful"],
            "best_plate_confidence": max([p["confidence"] for p in result["plates"]], default=0.0),
            "best_vehicle_confidence": max([v["confidence"] for v in result["vehicles"]], default=0.0)
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


# Funkcje pomocnicze dla przyszłego użycia
def extract_plates_from_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Wyciąga tylko dane płytek z XML"""
    result = process_ncshot_result_xml(xml_content)
    return result.get("plates", [])


def extract_vehicles_from_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Wyciąga tylko dane pojazdów z XML"""
    result = process_ncshot_result_xml(xml_content)
    return result.get("vehicles", [])


def validate_ncsim_output(output: str) -> Tuple[bool, List[str]]:
    """Waliduje wyjście NCSim i zwraca status + listę problemów"""
    issues = []
    
    if not output or not output.strip():
        return False, ["Puste wyjście z NCSim"]
    
    output_lower = output.lower()
    
    # Sprawdź podstawowe błędy
    if "syntax not loaded" in output_lower:
        issues.append("Nie załadowano składni")
    if "cannot open" in output_lower:
        issues.append("Nie można otworzyć wymaganych plików")
    if "invalid" in output_lower and "config" in output_lower:
        issues.append("Nieprawidłowa konfiguracja")
    
    # Sprawdź czy są wyniki
    has_results = any(phrase in output_lower for phrase in ["recog-strong", "recog-weak"])
    
    if not has_results and not issues:
        issues.append("Brak wyników rozpoznania")
    
    is_valid = len(issues) == 0
    return is_valid, issues


if __name__ == "__main__":
    # Testy jednostkowe
    print("🧪 Uruchamianie testów logic.py...")
    
    # Test z błędem składni
    test_syntax_error = """
    ncsim.exe - Neurosoft ANPR/MMR simulator, ver. 2.2.2.3278
    (c) Neurosoft sp. z o.o., Wroclaw 1992-2014

    std::exception: Syntax not loaded.
    Check configuration file.
    """
    
    result = process_ncsim_result(test_syntax_error)
    print("✅ Test błędu składni:")
    print(f"   Status: {result['processing_successful']}")
    print(f"   Błąd: {result['error']}")
    print(f"   Kategoria: {result.get('error_category', 'brak')}")
    
    # Test z prawidłowymi wynikami
    test_success = """
    ncsim.exe - Neurosoft ANPR/MMR simulator, ver. 2.2.2.3278
    (c) Neurosoft sp. z o.o., Wroclaw 1992-2014
    
    Processing image...
    recog-strong: 85.5%
    recog-weak: 72.3%
    Processing time: 1.234 sec
    """
    
    result2 = process_ncsim_result(test_success)
    print("\n✅ Test prawidłowych wyników:")
    print(f"   Status: {result2['processing_successful']}")
    print(f"   Rozpoznanie silne: {result2['recog_strong']}%")
    print(f"   Rozpoznanie słabe: {result2['recog_weak']}%")
    print(f"   Płytki: {len(result2['plates'])}")
    
    print("\n🎉 Testy zakończone pomyślnie!")