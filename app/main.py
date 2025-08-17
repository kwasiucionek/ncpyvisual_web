# app/main.py - POPRAWIONY bez problemów z pamięcią
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
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

from .logic import process_ncsim_result

# Konfiguracja maszyny wirtualnej
VM_HOST = os.getenv("VM_HOST", "192.168.122.228")
VM_USER = os.getenv("VM_HOST_USER", "root")
VM_PASS = os.getenv("VM_HOST_PASS")

# Konfiguracja ncshot
NCSHOT_HOST = VM_HOST
NCSHOT_PORT = int(os.getenv("NCSHOT_PORT", "5543"))

if not VM_PASS:
    logging.warning("⚠️ Brak VM_HOST_PASS w zmiennych środowiskowych!")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('ncpyvisual.log')
    ]
)

# Ścieżka do lokalnego pliku ncsim
NCSIM_LOCAL_PATH = "bin/ncsim"

# Konfiguracja limitu obrazów (NOWE ZABEZPIECZENIE)
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB maksymalny rozmiar obrazu
MIN_IMAGE_SIZE = 1024  # 1KB minimalny rozmiar

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

class VerifyBody(BaseModel):
    package: FullPackage
    password: Optional[str] = None
    terminal_ip: str
    image_base64: str

class NcshotRequest(BaseModel):
    package: FullPackage
    image_files: List[str]

# ===== APP =====
app = FastAPI(title="NCPyVisual Web")
templates = Jinja2Templates(directory="app/templates")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logging.error(f"❌ Błąd walidacji dla {request.url.path}:")
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

# ===== POPRAWIONY GENERATOR KONFIGURACJI INI =====
def build_roi_config_ini(package: FullPackage) -> str:
    """Generator pliku INI - używa sprawdzonego formatu z VM"""
    config_names = ["main"]
    if len(package.rois) > 1:
        config_names.extend([f"alt{i:02d}" for i in range(1, len(package.rois))])

    ini_content = f"[global]\nconfigurations = {' '.join(config_names)}\n\n"
    
    # Common section - DOKŁADNIE jak na VM
    ini_content += """[common]
plate.ref.width = 96
required.probability = 0.65
plate.ref.height = 18

; Parametry systemowe - używamy ścieżek z VM
syntax.folder = /neurocar/etc/syntax
dta.file = /neurocar/etc/classreco77k-2016-07-29.dta
log.file = /dev/null
log.level = debug

"""

    # Configuration sections
    for config_name in config_names:
        ini_content += f"[{config_name}]\nplaterecognizer = platerecognizer-{config_name}\nclassrecognizer = classrecognizer-{config_name}\n\n"

    # Platerecognizer sections - format DOKŁADNIE jak na VM
    for i, (config_name, roi) in enumerate(zip(config_names, package.rois)):
        ini_content += f"[platerecognizer-{config_name}]\n"
        
        # ROI points - konwersja do pikseli
        if roi.points and len(roi.points) >= 3:
            roi_points_pixels = []
            for p in roi.points:
                # Konwersja względnych współrzędnych (0-1) na piksele (2560x2560)
                x = int(float(p['x']) * 2560) if p['x'] <= 1.0 else int(float(p['x']))
                y = int(float(p['y']) * 2560) if p['y'] <= 1.0 else int(float(p['y']))
                roi_points_pixels.append(f"{x},{y}")
            ini_content += f"roi = {';'.join(roi_points_pixels)}\n"
        else:
            # Domyślny ROI jeśli brak punktów
            ini_content += "roi = 234,1410;13,1127;6,566;1058,517;2236,805\n"

        # Parametry - format dokładnie jak na VM
        ini_content += f"skew.h = {float(roi.skewH):.1f}\n"
        ini_content += f"skew.v = {float(roi.skewV):.1f}\n"
        ini_content += f"angle = {float(roi.angle):.1f}\n"
        
        # Zoom - sprawdzone wartości domyślne z VM
        zoom_val = float(roi.zoom) if roi.zoom > 0 else (0.035 if config_name == "main" else 0.039)
        ini_content += f"zoom = {zoom_val:.3f}\n"
        
        # Tylko dla main konfiguracji - dokładnie jak na VM
        if config_name == "main":
            ini_content += f"reflex.offset.h = {int(roi.reflexOffsetH)}\n"
            ini_content += f"reflex.offset.v = {int(roi.reflexOffsetV)}\n"
            ini_content += "algorithms = neuronet.signature\n"
        
        ini_content += "\n"

    # Classrecognizer sections - dokładnie jak na VM
    for config_name in config_names:
        ini_content += f"[classrecognizer-{config_name}]\n"
        for param in ['skew.h', 'skew.v', 'angle', 'zoom']:
            ini_content += f"{param} = %(platerecognizer-{config_name}/{param})\n"
        ini_content += "\n"
        
    return ini_content

# ===== NOWE FUNKCJE WALIDACJI OBRAZÓW =====
def validate_image_data(image_data: bytes, image_index: int) -> bool:
    """Waliduje dane obrazu przed wysłaniem do NCShot"""
    
    # Sprawdź rozmiar
    if len(image_data) < MIN_IMAGE_SIZE:
        logging.error(f"❌ Obraz {image_index}: zbyt mały ({len(image_data)} bajtów)")
        return False
    
    if len(image_data) > MAX_IMAGE_SIZE:
        logging.error(f"❌ Obraz {image_index}: zbyt duży ({len(image_data)} bajtów > {MAX_IMAGE_SIZE})")
        return False
    
    # Sprawdź nagłówek JPEG
    if not image_data.startswith(b'\xff\xd8'):
        logging.error(f"❌ Obraz {image_index}: nieprawidłowy nagłówek JPEG")
        return False
    
    # Sprawdź końcówkę JPEG
    if not image_data.endswith(b'\xff\xd9'):
        logging.warning(f"⚠️ Obraz {image_index}: brak końcówki JPEG, ale kontynuuję")
    
    logging.info(f"✅ Obraz {image_index}: walidacja przeszła pomyślnie ({len(image_data)} bajtów)")
    return True

def optimize_image_for_ncshot(image_data: bytes) -> bytes:
    """Optymalizuje obraz dla NCShot (jeśli potrzeba)"""
    # Jeśli obraz jest za duży, możemy w przyszłości dodać kompresję
    # Na razie tylko zwracamy oryginalny
    return image_data

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
    logging.info(f"🔧 Wykonuję: {command}")
    try:
        stdin, stdout, stderr = dev.exec_command(command, timeout=30)
        stdout_str = stdout.read().decode('utf-8', 'ignore').strip()
        stderr_str = stderr.read().decode('utf-8', 'ignore').strip()

        if stdout_str:
            logging.info(f"  ✅ [STDOUT]: {stdout_str[:200]}{'...' if len(stdout_str) > 200 else ''}")
        if stderr_str:
            logging.warning(f"  ⚠️ [STDERR]: {stderr_str[:200]}{'...' if len(stderr_str) > 200 else ''}")

        return stdout_str, stderr_str
    except Exception as e:
        logging.error(f"  ❌ Błąd wykonania komendy: {e}")
        return "", str(e)

# ===== FUNKCJA NCSIM =====
async def verify_roi_with_ncsim(dev: paramiko.SSHClient, sftp: paramiko.SFTPClient, package: FullPackage, image_base64: str):
    """Weryfikuje scenę używając NCSim"""
    timestamp = int(time.time())
    temp_dir = f"/tmp/ncpyvisual_test_{timestamp}"

    if not os.path.exists(NCSIM_LOCAL_PATH):
        raise HTTPException(status_code=500, detail=f"Brak pliku ncsim w lokalizacji: {NCSIM_LOCAL_PATH}")

    try:
        logging.info("🔬 Uruchamianie NCSim (weryfikacja opcjonalna)")
        execute_and_log(dev, f"mkdir -p {temp_dir}")

        # Skopiuj ncsim
        sftp.put(NCSIM_LOCAL_PATH, f"{temp_dir}/ncsim")
        execute_and_log(dev, f"chmod +x {temp_dir}/ncsim")

        # Używaj generatora konfiguracji
        config_ini = build_roi_config_ini(package)
        logging.info(f"📋 Konfiguracja NCSim ({len(config_ini)} znaków)")

        # Zapisz konfigurację
        sftp.putfo(io.BytesIO(config_ini.encode('utf-8')), f"{temp_dir}/config.ini")

        # Dekoduj i wyślij obraz
        try:
            if image_base64.startswith('data:image'):
                header, data = image_base64.split(',', 1)
                image_data = base64.b64decode(data)
            else:
                image_data = base64.b64decode(image_base64)
            
            # Sprawdź czy to prawidłowy JPEG
            if not image_data.startswith(b'\xff\xd8'):
                raise Exception("Nieprawidłowy format JPEG")
                
        except Exception as e:
            logging.error(f"❌ Błąd dekodowania obrazu: {e}")
            raise HTTPException(status_code=400, detail=f"Błąd dekodowania obrazu: {e}")
        
        sftp.putfo(io.BytesIO(image_data), f"{temp_dir}/test_image.jpg")
        logging.info(f"🖼️ Obraz zapisany: {len(image_data)} bajtów")

        # Uruchom ncsim
        logging.info("🚀 Uruchamianie NCSim...")
        command = f"cd {temp_dir} && ./ncsim -mconfig.ini test_image.jpg 2>&1"
        ncsim_output, ncsim_error = execute_and_log(dev, command)

        # Połącz wyjście
        full_output = ncsim_output + "\n" + ncsim_error
        logging.info(f"📊 NCSim zakończony")

        # Sprawdź czy to błąd składni
        if "Syntax not loaded" in full_output:
            return {
                "verification_type": "ncsim_verification", 
                "processing_method": "NCSim - błąd składni (NCShot pozostaje główną funkcją)",
                "results": {
                    "processing_successful": False,
                    "error": "INFORMACJA: NCSim wymaga plików składni .bin które nie są dostępne na tej maszynie wirtualnej. To nie wpływa na działanie NCShot.",
                    "ncsim_output": full_output,
                    "recog_strong": None,
                    "recog_weak": None,
                    "processing_time": None,
                    "note": "NCShot działa poprawnie niezależnie od NCSim"
                }
            }

        # Jeśli nie ma błędu składni, parsuj normalnie
        return {
            "verification_type": "ncsim_verification", 
            "processing_method": "NCSim - weryfikacja udana",
            "results": process_ncsim_result(full_output)
        }
        
    except Exception as e:
        logging.error(f"💥 Błąd w NCSim: {e}")
        return {
            "verification_type": "ncsim_verification", 
            "processing_method": "NCSim - błąd uruchomienia",
            "results": {
                "processing_successful": False,
                "error": f"Błąd uruchomienia NCSim: {str(e)} (NCShot pozostaje dostępny)",
                "ncsim_output": f"BŁĄD: {str(e)}",
                "recog_strong": None,
                "recog_weak": None,
                "processing_time": None,
                "note": "NCShot jest główną funkcjonalnością i działa niezależnie od NCSim"
            }
        }
    finally:
        if dev: 
            execute_and_log(dev, f"rm -rf {temp_dir}")

# ===== GŁÓWNA POPRAWIONA FUNKCJA NCSHOT =====
def start_ncshot_with_config_safe(package: FullPackage, image_files: List[str]) -> Dict[str, Any]:
    """
    BEZPIECZNA GŁÓWNA FUNKCJONALNOŚĆ - Uruchamia ncshot bez problemów z pamięcią
    Bazuje na sprawdzonej wersji z dodatkowymi zabezpieczeniami
    """
    logging.info(f"🚀 === NCSHOT - BEZPIECZNA WERSJA ===")
    logging.info(f"   🌐 VM: {NCSHOT_HOST}:{NCSHOT_PORT}")
    logging.info(f"   📸 Liczba obrazów: {len(image_files)}")
    logging.info(f"   🎯 Liczba ROI: {len(package.rois)}")

    vm_ssh = None
    try:
        # 1. Połącz się z maszyną wirtualną przez SSH
        vm_ssh = connect_to_vm()
        vm_sftp = vm_ssh.open_sftp()
        
        # 2. Wygeneruj konfigurację INI
        ini_config = build_roi_config_ini(package)
        logging.info(f"📋 Wygenerowana konfiguracja INI ({len(ini_config)} znaków)")
        
        # 3. Skopiuj konfigurację na maszynę wirtualną (PROSTY sposób)
        config_path = "/neurocar/etc/ncshot.d/tmp.ini"
        logging.info(f"📤 Kopiuję konfigurację do: {config_path}")
        
        # Utwórz katalog jeśli nie istnieje
        execute_and_log(vm_ssh, "mkdir -p /neurocar/etc/ncshot.d")
        
        # Zapisz konfigurację
        vm_sftp.putfo(io.BytesIO(ini_config.encode('utf-8')), config_path)
        logging.info(f"✅ Konfiguracja zapisana na VM")
        
        # Sprawdź czy plik został zapisany
        stdout, stderr = execute_and_log(vm_ssh, f"ls -la {config_path}")
        if "tmp.ini" not in stdout:
            raise Exception(f"Nie udało się zapisać pliku konfiguracyjnego: {stderr}")
        
        vm_sftp.close()
        vm_ssh.close()
        vm_ssh = None
        
        # 4. PROSTY test dostępności NCShot (bez restartu!)
        logging.info(f"🔍 Sprawdzanie dostępności NCShot HTTP API...")
        try:
            test_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=10)
            test_hc.request("GET", "/")
            test_resp = test_hc.getresponse()
            test_content = test_resp.read().decode('utf-8', 'ignore')
            test_hc.close()
            logging.info(f"✅ NCShot HTTP API odpowiada: {test_resp.status}")
        except Exception as e:
            logging.error(f"❌ NCShot HTTP API nie odpowiada: {e}")
            raise HTTPException(status_code=503, detail=f"NCShot nie jest dostępny: {e}")

        # 5. Wyślij konfigurację przez HTTP (KLUCZ DO SUKCESU)
        try:
            logging.info("📤 Wysyłam konfigurację do NCShot przez HTTP API...")
            config_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=30)
            config_hc.request("PUT", "/config/tmp", ini_config.encode('utf-8'), {
                "Content-Type": "text/plain",
                "Content-Length": str(len(ini_config.encode('utf-8')))
            })
            config_resp = config_hc.getresponse()
            config_content = config_resp.read().decode('utf-8', 'ignore')
            config_hc.close()
            
            if config_resp.status != 200:
                logging.error(f"❌ NCShot odrzucił konfigurację: {config_resp.status} - {config_content}")
                raise HTTPException(status_code=500, detail=f"NCShot odrzucił konfigurację: {config_content}")
            else:
                logging.info("✅ Konfiguracja zaakceptowana przez NCShot")
        except HTTPException:
            raise
        except Exception as e:
            logging.error(f"❌ Błąd wysyłania konfiguracji przez HTTP: {e}")
            raise HTTPException(status_code=500, detail=f"Błąd konfiguracji NCShot: {e}")

        # 6. Teraz BEZPIECZNIE przetwórz obrazy
        result = {}
        tokens = []
        failed_images = 0

        for i, image_b64 in enumerate(image_files):
            try:
                logging.info(f"🖼️ === PRZETWARZANIE OBRAZU {i+1}/{len(image_files)} ===")
                
                # BEZPIECZNE dekodowanie obrazu
                try:
                    if image_b64.startswith('data:image'):
                        # Usuń prefiks data:image/jpeg;base64,
                        header, data = image_b64.split(',', 1)
                        image_data = base64.b64decode(data)
                    else:
                        image_data = base64.b64decode(image_b64)
                    
                    # NOWA WALIDACJA OBRAZU
                    if not validate_image_data(image_data, i):
                        failed_images += 1
                        continue
                    
                    # Optymalizuj obraz dla NCShot
                    image_data = optimize_image_for_ncshot(image_data)
                        
                except Exception as e:
                    logging.error(f"❌ Błąd dekodowania obrazu {i}: {e}")
                    failed_images += 1
                    continue
                
                logging.info(f"📊 Wysyłanie obrazu: {len(image_data)} bajtów")
                
                # Wyślij obraz do ncshot (PROSTY sposób)
                hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=60)
                
                # BEZPIECZNE wysyłanie z odpowiednimi nagłówkami
                hc.request("PUT", "/tmp?anpr=1&mmr=1&diagnostic=1", image_data, {
                    "Content-Type": "image/jpeg",
                    "Content-Length": str(len(image_data)),
                    "Connection": "close"  # NOWE - wymusza zamknięcie połączenia
                })
                resp = hc.getresponse()
                
                logging.info(f"📸 Odpowiedź dla obrazu {i}: {resp.status} {resp.reason}")
                
                if resp.status != 200:
                    error_content = resp.read().decode('utf-8', 'ignore')
                    logging.error(f"❌ Błąd przetwarzania obrazu {i}: {resp.status} - {error_content}")
                    hc.close()
                    failed_images += 1
                    
                    # WAŻNE: Jeśli to błąd pamięci, przerwij
                    if "bad_alloc" in error_content or "Internal Server Error" in error_content:
                        logging.error("💥 Wykryto błąd pamięci w NCShot - przerywam przetwarzanie")
                        break
                    
                    continue

                token = resp.getheader("ncshot-token")
                xml_content = resp.read().decode('utf-8')
                
                if token:
                    tokens.append(token)
                    logging.info(f"🎫 Otrzymano token: {token}")
                
                logging.info(f"📄 Otrzymano XML ({len(xml_content)} znaków)")

                file_result = {
                    "xml": xml_content,
                    "plates": []
                }

                # Pobierz obrazy płytek (tylko jeśli mamy token)
                if token:
                    try:
                        root = ET.fromstring(xml_content)
                        exdata_elements = root.findall(".//exdata")
                        exdata_count = len(exdata_elements)
                        logging.info(f"🔍 Znaleziono {exdata_count} elementów exdata")

                        for j in range(1, exdata_count + 1):
                            try:
                                plate_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=30)
                                plate_url = f"/vehicleplate?token={token}&number={j}"
                                
                                plate_hc.request("GET", plate_url)
                                plate_resp = plate_hc.getresponse()
                                plate_data = plate_resp.read()
                                
                                logging.info(f"📸 Płytka {j}: {plate_resp.status}, {len(plate_data)} bajtów")
                                
                                if plate_resp.status == 200 and plate_data and len(plate_data) > 0:
                                    if plate_data.startswith(b'\xff\xd8'):
                                        plate_b64 = base64.b64encode(plate_data).decode('utf-8')
                                        file_result["plates"].append(f"data:image/jpeg;base64,{plate_b64}")
                                        logging.info(f"✅ Pobrano płytkę {j}")
                                    else:
                                        logging.warning(f"⚠️ Płytka {j} nie jest JPEG")
                                        file_result["plates"].append(None)
                                else:
                                    logging.warning(f"⚠️ Błąd płytki {j}: {plate_resp.status}")
                                    file_result["plates"].append(None)
                                
                                plate_hc.close()
                            except Exception as plate_error:
                                logging.error(f"❌ EXCEPTION płytka {j}: {plate_error}")
                                file_result["plates"].append(None)

                    except Exception as e:
                        logging.error(f"❌ Błąd parsowania XML: {e}")

                result[f"image_{i}"] = file_result
                hc.close()

            except Exception as e:
                logging.error(f"❌ KRYTYCZNY BŁĄD obrazu {i}: {e}")
                failed_images += 1
                continue

        # Zwolnij tokeny (WAŻNE dla pamięci)
        for token in tokens:
            try:
                release_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=10)
                release_hc.request("GET", f"/release?token={token}")
                release_resp = release_hc.getresponse()
                release_resp.read()
                release_hc.close()
                logging.info(f"🔓 Token {token} zwolniony")
            except Exception as e:
                logging.error(f"⚠️ Błąd zwalniania tokenu {token}: {e}")

        logging.info(f"✅ === NCSHOT ZAKOŃCZONY ===")
        logging.info(f"   📊 Pomyślnie: {len(result)} obrazów")
        logging.info(f"   ❌ Błędy: {failed_images} obrazów")
        
        # Dodaj statystyki do wyniku
        result["_stats"] = {
            "processed": len(result) - 1,  # -1 bo _stats nie jest obrazem
            "failed": failed_images,
            "total": len(image_files)
        }
        
        return result

    except Exception as e:
        logging.error(f"❌ KRYTYCZNY BŁĄD NCShot: {e}")
        raise e
    finally:
        if vm_ssh:
            vm_ssh.close()

# ===== FUNKCJE TERMINALA =====
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

def fetch_images_from_device(device_ip: str, device_pass: Optional[str], count: int) -> List[Dict[str,str]]:
    jump = dev = None
    try:
        jump, dev = open_via_jump(device_ip, device_pass)
        sftp = dev.open_sftp()
        base = "/neurocar/data/deleted"
        items = sftp.listdir_attr(base)
        dirs = [d for d in items if stat.S_ISDIR(d.st_mode)]
        if not dirs: 
            return []
        
        latest = max(dirs, key=lambda d: d.st_mtime).filename
        folder = f"{base}/{latest}"
        files = sorted([f for f in sftp.listdir_attr(folder) if f.filename.endswith('.7z')],
                      key=lambda f: f.st_mtime, reverse=True)[:count]
        imgs = []
        
        for fa in files:
            with sftp.open(f"{folder}/{fa.filename}", 'rb') as f: 
                data = f.read()
            buf = io.BytesIO(data)
            image_bytes = None
            try:
                with py7zr.SevenZipFile(buf, mode='r') as z:
                    file_list = z.list()
                    jpg_filename = None
                    for file_info in file_list:
                        if file_info.filename.lower().endswith(('.jpg', '.jpeg')):
                            jpg_filename = file_info.filename
                            break
                    if jpg_filename:
                        with tempfile.TemporaryDirectory() as temp_dir:
                            z.extractall(path=temp_dir)
                            temp_file_path = os.path.join(temp_dir, jpg_filename)
                            if os.path.exists(temp_file_path):
                                with open(temp_file_path, 'rb') as img_file:
                                    image_bytes = img_file.read()
                                    
                                    # NOWA WALIDACJA także dla obrazów z urządzenia
                                    if validate_image_data(image_bytes, len(imgs)):
                                        imgs.append({ 
                                            "filename": fa.filename, 
                                            "data": "data:image/jpeg;base64,"+base64.b64encode(image_bytes).decode('utf-8'),
                                            "size": len(image_bytes)
                                        })
                                        logging.info(f"✅ Dodano obraz z urządzenia: {fa.filename}")
                                    else:
                                        logging.warning(f"⚠️ Odrzucono nieprawidłowy obraz: {fa.filename}")
            except Exception as e:
                logging.error(f"Błąd przy dekompresji {fa.filename}: {e}")
                
        sftp.close()
        return imgs
    finally:
        if dev: 
            dev.close()
        if jump: 
            jump.close()

# ===== INICJALIZACJA =====
app_start_time = time.time()

@app.on_event("startup")
async def startup_event():
    """Wykonuje inicjalizację przy starcie aplikacji"""
    global app_start_time
    app_start_time = time.time()
    logging.info("🎉 NCPyVisual Web Application uruchomiona (wersja bezpieczna)")

@app.on_event("shutdown")
async def shutdown_event():
    """Wykonuje cleanup przy wyłączaniu aplikacji"""
    logging.info("🛑 Zamykanie NCPyVisual Web Application...")
    logging.info("✅ Aplikacja zamknięta")

# ===== ROUTES =====
@app.get("/", response_class=HTMLResponse)
async def root(req: Request):
    return templates.TemplateResponse("index.html", {"request": req})

@app.get("/health/")
async def health_check():
    """Endpoint sprawdzania stanu systemu"""
    try:
        # Test połączenia z NCShot
        ncshot_status = "unknown"
        try:
            test_hc = httplib.HTTPConnection(NCSHOT_HOST, NCSHOT_PORT, timeout=5)
            test_hc.request("GET", "/")
            test_resp = test_hc.getresponse()
            test_resp.read()
            test_hc.close()
            ncshot_status = "ok" if test_resp.status == 200 else f"error_{test_resp.status}"
        except Exception as e:
            ncshot_status = f"unreachable: {str(e)}"

        config_status = {
            "vm_host": VM_HOST,
            "vm_user": VM_USER,
            "vm_pass_configured": bool(VM_PASS),
            "ncshot_host": NCSHOT_HOST,
            "ncshot_port": NCSHOT_PORT,
            "ncshot_status": ncshot_status
        }

        return {
            "status": "healthy" if ncshot_status == "ok" else "degraded",
            "version": "2.9.0-safe-memory-optimized",
            "main_functionality": "NCShot (bezpieczna wersja)",
            "optional_verification": "NCSim",
            "config": config_status,
            "limits": {
                "max_image_size_mb": MAX_IMAGE_SIZE // (1024*1024),
                "min_image_size_kb": MIN_IMAGE_SIZE // 1024
            },
            "logic_import": "OK",
            "models": "OK",
            "timestamp": datetime.now().isoformat(),
            "uptime": time.time() - app_start_time
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.post("/verify-scene/")
async def verify_scene_endpoint(body: VerifyBody):
    logging.info("🎯 Rozpoczynam weryfikację sceny z NCSim (opcjonalną)...")
    jump, dev, sftp = None, None, None
    try:
        if not body.image_base64:
            raise HTTPException(status_code=400, detail="Do weryfikacji ncsim wymagany jest obraz.")
        jump, dev = open_via_jump(body.terminal_ip, body.password)
        sftp = dev.open_sftp()
        recognition_data = await verify_roi_with_ncsim(dev, sftp, body.package, body.image_base64)
        return JSONResponse({"parsed_recognition_data": recognition_data, "success": True})
    except Exception as e:
        logging.error(f"Błąd krytyczny w /verify-scene/: {e}\n{traceback.format_exc()}")
        if isinstance(e, HTTPException): 
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if sftp: 
            sftp.close()
        if dev: 
            dev.close()
        if jump: 
            jump.close()

@app.post("/ncshot/")
async def ncshot_endpoint(body: NcshotRequest):
    """🚀 GŁÓWNA FUNKCJONALNOŚĆ - Endpoint dla ncshot (BEZPIECZNY)"""
    logging.info("🚀 === URUCHAMIANIE GŁÓWNEJ FUNKCJONALNOŚCI NCSHOT (BEZPIECZNA) ===")
    logging.info(f"   📊 ROI: {len(body.package.rois)}")
    logging.info(f"   🖼️ Obrazy: {len(body.image_files)}")

    try:
        if not body.image_files:
            raise HTTPException(status_code=400, detail="Wymagane są obrazy do przetworzenia.")

        if not body.package.deployment.locationId:
            raise HTTPException(status_code=400, detail="Wymagane jest ID lokalizacji.")

        # Sprawdź liczebność obrazów (zabezpieczenie przed przeciążeniem)
        if len(body.image_files) > 20:
            raise HTTPException(status_code=400, detail="Maksymalnie 20 obrazów na raz (zabezpieczenie pamięci)")

        # 🚀 GŁÓWNA FUNKCJONALNOŚĆ - UŻYWAMY BEZPIECZNEJ WERSJI
        results = start_ncshot_with_config_safe(body.package, body.image_files)
        logging.info(f"✅ === NCSHOT ZAKOŃCZONY POMYŚLNIE - {len(results)-1} wyników ===")
        return JSONResponse({"results": results, "success": True})

    except Exception as e:
        logging.error(f"❌ Błąd krytyczny w głównej funkcjonalności NCShot: {e}\n{traceback.format_exc()}")
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
            logging.warning(f"⚠️ Ograniczono liczbę obrazów do {count} (zabezpieczenie)")
            
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
            readme = f"# Pakiet konfiguracyjny dla {pkg.deployment.locationId}\n\nGłówna funkcjonalność: NCShot (bezpieczna wersja)\nWeryfikacja opcjonalna: NCSim\nLimity: max {MAX_IMAGE_SIZE//1024//1024}MB na obraz"
            z.writestr("README.txt", readme)
        ts = time.strftime("%Y%m%d-%H%M%S")
        name = f"ncpy_package_{pkg.deployment.locationId}_{ts}.zip"
        return StreamingResponse(
            iter([buf.getvalue()]), 
            media_type="application/x-zip-compressed", 
            headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania pakietu: {e}")

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
