# app/main.py - KOMPLETNY KOD Z POPRAWIONĄ OBSŁUGĄ NCSHOT PRZEZ SSH TUNNEL
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Tuple
import xml.etree.ElementTree as ET
from xml.dom import minidom
import io, zipfile, time, os, stat, base64, tempfile, re, logging, traceback
import configparser
import paramiko
import py7zr
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import socket
import threading
import random

# Import relatywny
from .logic import process_ncsim_result, process_ncshot_result_xml

# Ustawienie podstawowej konfiguracji logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Ścieżka do lokalnego pliku ncsim, który będziemy wysyłać
NCSIM_LOCAL_PATH = "bin/ncsim"

# Konfiguracja ncshot - teraz na terminalu docelowym
NCSHOT_PORT = "5543"  # Port na terminalu docelowym
NCSHOT_TIMEOUT = 30   # sekundy

# ===== MODELE =====
class RoiData(BaseModel):
    id: str
    points: List[Dict[str, float]]
    angle: float
    zoom: float
    reflexOffsetH: int
    reflexOffsetV: int
    skewH: float
    skewV: float

class DeploymentConfig(BaseModel):
    serialNumber: str
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

# ===== APP =====
app = FastAPI(title="NCPyVisual Web")
templates = Jinja2Templates(directory="app/templates")

# ===== GENERATORY PLIKÓW =====
def build_roi_config_ini(package: FullPackage, relative_paths: bool = False) -> str:
    """
    Generuje plik INI. Jeśli relative_paths=True, ścieżki do syntax i dta są względne.
    """
    config_names = ["main"]
    if len(package.rois) > 1:
        config_names.extend([f"alt{i:02d}" for i in range(1, len(package.rois))])

    syntax_folder = "syntax" if relative_paths else "/neurocar/etc/syntax"
    dta_file = "classreco77k-2016-07-29.dta" if relative_paths else "/neurocar/etc/classreco77k-2016-07-29.dta"

    ini_content = f"[global]\nconfigurations = {' '.join(config_names)}\n\n"
    ini_content += f"""; Parametry systemowe
syntax.folder = {syntax_folder}
dta.file = {dta_file}
log.file = /dev/null
log.level = debug

[common]
plate.ref.width = 96
required.probability = 0.65
plate.ref.height = 18

"""
    for config_name in config_names:
        ini_content += f"[{config_name}]\nplaterecognizer = platerecognizer-{config_name}\nclassrecognizer = classrecognizer-{config_name}\n\n"

    for i, (config_name, roi) in enumerate(zip(config_names, package.rois)):
        ini_content += f"[platerecognizer-{config_name}]\n"
        if roi.points and len(roi.points) >= 3:
            roi_points_pixels = [f"{int(p['x'] * 2560)},{int(p['y'] * 2560)}" for p in roi.points]
            ini_content += f"roi = {';'.join(roi_points_pixels)}\n"

        ini_content += f"skew.h = {roi.skewH}\nskew.v = {roi.skewV}\nangle = {roi.angle}\nzoom = {roi.zoom}\n"
        ini_content += f"reflex.offset.h = {roi.reflexOffsetH}\nreflex.offset.v = {roi.reflexOffsetV}\n"
        ini_content += "autolevel = 5\nmax.candidates = 5\nrequired.probability = 0.69\nanisotropy = 1.0\n"
        
        if config_name == "main":
            ini_content += "algorithms = neuronet.signature\nneuronet.syntax.order = +omni (pl de gb cz ua sk at ro by ru nl - bg fr ie es tr) +pl (pl) +baltic (dk ee lv no lt) de (de) by (by) cz (cz) gb (gb) at (at) ua (ua) ru (ru)\n"
        ini_content += "\n"

    for config_name in config_names:
        ini_content += f"[classrecognizer-{config_name}]\n"
        for param in ['skew.h', 'skew.v', 'angle', 'zoom']:
            ini_content += f"{param} = %(platerecognizer-{config_name}/{param})\n"
        ini_content += "foreshort.h = 0\nlocal.contrast.normalization = 0.0\nrotation.correction.threshold = 3.0\n\n"
    return ini_content

# ===== SSH & SFTP HELPERS =====
def open_via_jump(device_ip: str, device_pass: Optional[str]) -> Tuple[paramiko.SSHClient, paramiko.SSHClient]:
    JUMP_HOST = "10.10.33.113"
    JUMP_USER = os.getenv("JUMP_HOST_USER")
    JUMP_PASS = os.getenv("JUMP_HOST_PASS")
    if not JUMP_USER or not JUMP_PASS:
        raise HTTPException(status_code=500, detail="Brak JUMP_HOST_USER/JUMP_HOST_PASS.")

    jump = paramiko.SSHClient(); jump.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    logging.info(f"Łączenie z Jump Host: {JUMP_HOST}...")
    jump.connect(JUMP_HOST, username=JUMP_USER, password=JUMP_PASS, timeout=10)

    ch = jump.get_transport().open_channel("direct-tcpip", (device_ip,22), ('127.0.0.1',0))
    dev = paramiko.SSHClient(); dev.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    logging.info(f"Łączenie z terminalem docelowym: {device_ip}...")
    dev.connect(device_ip, sock=ch, username="root", password=device_pass, timeout=10)
    return jump, dev

def execute_and_log(dev: paramiko.SSHClient, command: str) -> Tuple[str, str]:
    logging.info(f"Wykonuję: {command}")
    stdin, stdout, stderr = dev.exec_command(command)
    stdout_str = stdout.read().decode('utf-8', 'ignore').strip()
    stderr_str = stderr.read().decode('utf-8', 'ignore').strip()
    if stdout_str: logging.info(f"  [STDOUT]: {stdout_str}")
    if stderr_str: logging.warning(f"  [STDERR]: {stderr_str}")
    return stdout_str, stderr_str

def create_ssh_tunnel(jump_ssh: paramiko.SSHClient, remote_host: str, remote_port: int, local_port: int = None) -> int:
    """
    Tworzy SSH tunnel przez jump host do terminala docelowego.
    Zwraca lokalny port na którym nasłuchuje tunel.
    """
    if local_port is None:
        # Znajdź wolny port lokalny
        local_port = random.randint(10000, 60000)
        while is_port_in_use(local_port):
            local_port = random.randint(10000, 60000)
    
    logging.info(f"🔀 Tworzę SSH tunnel: localhost:{local_port} -> {remote_host}:{remote_port}")
    
    # Utwórz tunel w osobnym wątku
    tunnel_thread = threading.Thread(
        target=_tunnel_worker,
        args=(jump_ssh, remote_host, remote_port, local_port),
        daemon=True
    )
    tunnel_thread.start()
    
    # Poczekaj chwilę na ustanowienie połączenia
    time.sleep(1)
    
    return local_port

def is_port_in_use(port: int) -> bool:
    """Sprawdza czy port jest zajęty"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def _tunnel_worker(jump_ssh: paramiko.SSHClient, remote_host: str, remote_port: int, local_port: int):
    """Worker function dla SSH tunnel w osobnym wątku"""
    try:
        # Utwórz socket lokalny
        local_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        local_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        local_socket.bind(('localhost', local_port))
        local_socket.listen(1)
        
        logging.info(f"🎧 Tunnel nasłuchuje na localhost:{local_port}")
        
        while True:
            client_socket, addr = local_socket.accept()
            logging.debug(f"📞 Połączenie tunnel z {addr}")
            
            try:
                # Utwórz kanał SSH do terminala docelowego
                remote_channel = jump_ssh.get_transport().open_channel(
                    "direct-tcpip",
                    (remote_host, remote_port),
                    addr
                )
                
                # Rozpocznij przekazywanie danych w obu kierunkach
                def forward_data(source, destination):
                    try:
                        while True:
                            data = source.recv(4096)
                            if not data:
                                break
                            destination.send(data)
                    except:
                        pass
                    finally:
                        source.close()
                        destination.close()
                
                # Uruchom przekazywanie w obu kierunkach
                threading.Thread(target=forward_data, args=(client_socket, remote_channel), daemon=True).start()
                threading.Thread(target=forward_data, args=(remote_channel, client_socket), daemon=True).start()
                
            except Exception as e:
                logging.error(f"Błąd w tunnel worker: {e}")
                client_socket.close()
                
    except Exception as e:
        logging.error(f"Błąd tworzenia tunnel: {e}")

# ===== NCSHOT HELPERS =====
def create_robust_session():
    """Tworzy sesję requests z retry i timeout"""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        method_whitelist=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"],
        backoff_factor=1
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

async def verify_roi_with_ncshot(package: FullPackage, image_base64: str, terminal_ip: str, password: Optional[str] = None):
    """
    Weryfikuje scenę przez ncshot API działający na terminalu docelowym.
    Używa SSH tunnel przez jump host do komunikacji z ncshot.
    """
    jump_ssh = None
    dev_ssh = None
    tunnel_port = None
    session = create_robust_session()
    token = None
    
    try:
        logging.info(f"🎯 Rozpoczynam weryfikację NCShot na terminalu {terminal_ip}:{NCSHOT_PORT}")
        
        # 1. Połącz się z jump host i terminalem docelowym
        jump_ssh, dev_ssh = open_via_jump(terminal_ip, password)
        
        # 2. Sprawdź czy ncshot działa na terminalu
        stdout, stderr = execute_and_log(dev_ssh, f"netstat -tlpn | grep :{NCSHOT_PORT}")
        if NCSHOT_PORT not in stdout:
            logging.warning(f"NCShot może nie działać na porcie {NCSHOT_PORT}")
        
        # 3. Utwórz SSH tunnel do ncshot na terminalu
        tunnel_port = create_ssh_tunnel(jump_ssh, terminal_ip, int(NCSHOT_PORT))
        logging.info(f"🔗 SSH tunnel utworzony: localhost:{tunnel_port} -> {terminal_ip}:{NCSHOT_PORT}")
        
        # 4. Sprawdź czy tunnel działa
        time.sleep(2)  # Daj czas na ustanowienie połączenia
        try:
            test_response = session.get(f"http://localhost:{tunnel_port}/", timeout=5)
            logging.info(f"✅ Tunnel działa, odpowiedź HTTP: {test_response.status_code}")
        except requests.exceptions.RequestException as e:
            logging.warning(f"⚠️ Test tunnel: {e}")
        
        # 5. Generuj konfigurację INI
        config_content = build_roi_config_ini(package, relative_paths=False)
        logging.info("📝 Wygenerowano konfigurację INI")
        
        # 6. Wyślij konfigurację do ncshot (przez tunnel)
        config_url = f"http://localhost:{tunnel_port}/config/tmp"
        logging.info(f"📤 Wysyłam konfigurację do {config_url}")
        
        config_response = session.put(
            config_url, 
            data=config_content,
            timeout=NCSHOT_TIMEOUT,
            headers={'Content-Type': 'text/plain'}
        )
        
        if config_response.status_code != 200:
            raise Exception(f"Błąd wysyłania konfiguracji: HTTP {config_response.status_code} - {config_response.text}")
        
        logging.info("✅ Konfiguracja wysłana pomyślnie")
        
        # 7. Przygotuj obraz
        if ',' in image_base64:
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)
        
        logging.info(f"🖼️ Przygotowano obraz ({len(image_data)} bajtów)")
        
        # 8. Wyślij obraz do analizy (przez tunnel)
        image_url = f"http://localhost:{tunnel_port}/tmp?anpr=1&mmr=1&diagnostic=1"
        logging.info(f"📤 Wysyłam obraz do {image_url}")
        
        image_response = session.put(
            image_url, 
            data=image_data,
            timeout=NCSHOT_TIMEOUT,
            headers={'Content-Type': 'image/jpeg'}
        )
        
        if image_response.status_code != 200:
            raise Exception(f"Błąd wysyłania obrazu: HTTP {image_response.status_code} - {image_response.text}")
        
        # 9. Pobierz token i XML z wynikami
        token = image_response.headers.get("ncshot-token")
        xml_result = image_response.text
        
        logging.info(f"✅ Otrzymano wynik (token: {token}, XML: {len(xml_result)} znaków)")
        
        if not xml_result.strip():
            raise Exception("NCShot zwrócił pusty wynik XML")
        
        # 10. Przetworz XML używając funkcji z logic.py
        results = process_ncshot_result_xml(xml_result)
        
        # 11. Opcjonalnie pobierz obrazy tablic (przez tunnel)
        plate_images = []
        if token and results.get("plates"):
            try:
                for i in range(1, len(results["plates"]) + 1):
                    plate_url = f"http://localhost:{tunnel_port}/vehicleplate?token={token}&number={i}"
                    plate_response = session.get(plate_url, timeout=10)
                    if plate_response.status_code == 200:
                        plate_b64 = base64.b64encode(plate_response.content).decode('utf-8')
                        plate_images.append(f"data:image/jpeg;base64,{plate_b64}")
                        logging.info(f"📷 Pobrano obraz tablicy {i}")
                
                # Dodaj obrazy do wyników
                for i, plate in enumerate(results.get("plates", [])):
                    if i < len(plate_images):
                        plate["image"] = plate_images[i]
            except Exception as e:
                logging.warning(f"Nie udało się pobrać obrazów tablic: {e}")
        
        return {
            "verification_type": "ncshot_verification", 
            "processing_method": f"NCShot przez SSH tunnel (localhost:{tunnel_port} -> {terminal_ip}:{NCSHOT_PORT})",
            "results": results,
            "token_used": token,
            "xml_response": xml_result,
            "tunnel_info": f"localhost:{tunnel_port}"
        }
        
    except requests.exceptions.Timeout:
        raise Exception(f"Timeout podczas komunikacji z ncshot ({NCSHOT_TIMEOUT}s)")
    except requests.exceptions.ConnectionError as e:
        raise Exception(f"Nie można połączyć się z ncshot przez tunnel: {str(e)}")
    except Exception as e:
        logging.error(f"Błąd ncshot: {e}")
        raise Exception(f"Błąd komunikacji z ncshot: {str(e)}")
    finally:
        # 12. Zwolnij token (przez tunnel)
        if token and tunnel_port:
            try:
                release_url = f"http://localhost:{tunnel_port}/release?token={token}"
                session.get(release_url, timeout=5)
                logging.info(f"🧹 Zwolniono token {token}")
            except Exception as e:
                logging.warning(f"Nie udało się zwolnić tokenu {token}: {e}")
        
        # 13. Zamknij połączenia SSH
        if dev_ssh: 
            dev_ssh.close()
            logging.info("🔐 Zamknięto połączenie SSH z terminalem")
        if jump_ssh: 
            jump_ssh.close()
            logging.info("🔐 Zamknięto połączenie SSH z jump host")

# ===== LOGIKA NCSIM (bez zmian) =====
async def verify_roi_with_ncsim(dev: paramiko.SSHClient, sftp: paramiko.SFTPClient, package: FullPackage, image_base64: str):
    """
    Weryfikuje scenę przez stworzenie kompletnego, samowystarczalnego środowiska dla ncsim.
    """
    timestamp = int(time.time())
    temp_dir = f"/tmp/ncpyvisual_test_{timestamp}"

    if not os.path.exists(NCSIM_LOCAL_PATH):
        raise HTTPException(status_code=500, detail=f"Brak pliku ncsim w lokalizacji: {NCSIM_LOCAL_PATH}")

    try:
        logging.info("🔬 Tworzenie kompletnego środowiska dla ncsim w %s", temp_dir)
        execute_and_log(dev, f"mkdir -p {temp_dir}")

        # 1. Kopiowanie zależności z /neurocar/etc do katalogu tymczasowego
        logging.info("Kopiowanie zależności (syntax, dta)...")
        execute_and_log(dev, f"cp -a /neurocar/etc/syntax {temp_dir}/syntax")
        execute_and_log(dev, f"cp /neurocar/etc/classreco77k-2016-07-29.dta {temp_dir}/")

        # 2. Wysłanie ncsim, obrazka i konfiguracji
        logging.info("Wysyłanie plików roboczych (ncsim, config, image)...")
        sftp.put(NCSIM_LOCAL_PATH, f"{temp_dir}/ncsim")
        execute_and_log(dev, f"chmod +x {temp_dir}/ncsim")

        # Generujemy konfigurację z ścieżkami względnymi
        config_content = build_roi_config_ini(package, relative_paths=True)
        sftp.putfo(io.StringIO(config_content), f"{temp_dir}/test_config.ini")
        
        if ',' in image_base64:
            image_data = base64.b64decode(image_base64.split(',')[1])
        else:
            image_data = base64.b64decode(image_base64)
        sftp.putfo(io.BytesIO(image_data), f"{temp_dir}/test_image.jpg")

        # 3. Uruchomienie ncsim z katalogu tymczasowego jako bieżącego
        command = f"cd {temp_dir} && ./ncsim -mtest_config.ini test_image.jpg"
        ncsim_output, ncsim_error = execute_and_log(dev, command)

        output = ncsim_output or ncsim_error
        if not output:
            raise Exception("NCSim nie zwrócił żadnych danych.")

        return {
            "verification_type": "ncsim_verification",
            "processing_method": "Uruchomienie w izolowanym środowisku",
            "results": process_ncsim_result(output)
        }
    finally:
        if dev: execute_and_log(dev, f"rm -rf {temp_dir}")
        logging.info("🧹 Zakończono weryfikację, posprzątano środowisko tymczasowe.")

# ===== ROUTES =====
@app.get("/", response_class=HTMLResponse)
async def root(req: Request):
    return templates.TemplateResponse("index.html", {"request": req})

@app.post("/verify-scene/")
async def verify_scene_endpoint(body: VerifyBody):
    """Weryfikacja przez ncsim (SSH)"""
    logging.info("🎯 Rozpoczynam weryfikację sceny z ncsim...")
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
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if sftp: sftp.close()
        if dev: dev.close()
        if jump: jump.close()

@app.post("/verify-scene-ncshot/")
async def verify_scene_ncshot_endpoint(body: VerifyBody):
    """Weryfikacja przez ncshot API (przez SSH tunnel)"""
    logging.info("🎯 Rozpoczynam weryfikację sceny z ncshot...")
    try:
        if not body.image_base64:
            raise HTTPException(status_code=400, detail="Do weryfikacji ncshot wymagany jest obraz.")
        
        recognition_data = await verify_roi_with_ncshot(
            body.package, 
            body.image_base64, 
            body.terminal_ip, 
            body.password
        )
        return JSONResponse({"parsed_recognition_data": recognition_data, "success": True})
        
    except Exception as e:
        logging.error(f"Błąd krytyczny w /verify-scene-ncshot/: {e}\n{traceback.format_exc()}")
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/import-from-device/")
async def import_from_device_endpoint(req: Request):
    try:
        data = await req.json()
        ip = data.get("ip"); pw = data.get("password")
        if not ip: raise HTTPException(status_code=400, detail="Brak IP terminala")
        # Ta funkcja nie istnieje, ale zostawiam jako placeholder
        # config = get_device_config(ip, pw)
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd importu: {e}")

@app.post("/fetch-device-images/")
async def fetch_device_images_endpoint(req: Request):
    try:
        data = await req.json()
        ip = data.get("ip"); pw = data.get("password"); count = int(data.get("count", 10))
        if not ip: raise HTTPException(status_code=400, detail="Brak IP terminala")
        # Ta funkcja nie istnieje, ale zostawiam jako placeholder
        # images = fetch_images_from_device(ip, pw, count)
        return JSONResponse({"images": []})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania obrazów: {e}")

@app.post("/generate-package/")
async def generate_package_endpoint(pkg: FullPackage):
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{pkg.deployment.locationId}.ini", build_roi_config_ini(pkg))
            readme = f"# Pakiet konfiguracyjny dla {pkg.deployment.locationId}"
            z.writestr("README.txt", readme)

        ts = time.strftime("%Y%m%d-%H%M%S")
        name = f"ncpy_package_{pkg.deployment.locationId}_{ts}.zip"
        return StreamingResponse(iter([buf.getvalue()]), media_type="application/x-zip-compressed", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania pakietu: {e}")
