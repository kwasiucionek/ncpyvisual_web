# app/main.py - KOMPLETNY KOD PO OSTATECZNEJ POPRAWCE
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

# Import relatywny
from .logic import process_ncsim_result

# Ustawienie podstawowej konfiguracji logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Ścieżka do lokalnego pliku ncsim, który będziemy wysyłać
NCSIM_LOCAL_PATH = "bin/ncsim"

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
        if config_name == "main":
            ini_content += "algorithms = neuronet.signature\n"
        ini_content += "\n"

    for config_name in config_names:
        ini_content += f"[classrecognizer-{config_name}]\n"
        for param in ['skew.h', 'skew.v', 'angle', 'zoom']:
            ini_content += f"{param} = %(platerecognizer-{config_name}/{param})\n"
        ini_content += "\n"
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

# ===== LOGIKA APLIKACJI =====
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
        # `cp -a` zachowuje strukturę i uprawnienia
        execute_and_log(dev, f"cp -a /neurocar/etc/syntax {temp_dir}/syntax")
        execute_and_log(dev, f"cp /neurocar/etc/classreco77k-2016-07-29.dta {temp_dir}/")

        # 2. Wysłanie ncsim, obrazka i konfiguracji
        logging.info("Wysyłanie plików roboczych (ncsim, config, image)...")
        sftp.put(NCSIM_LOCAL_PATH, f"{temp_dir}/ncsim")
        execute_and_log(dev, f"chmod +x {temp_dir}/ncsim")

        # Generujemy konfigurację z ścieżkami względnymi
        config_content = build_roi_config_ini(package, relative_paths=True)
        sftp.putfo(io.StringIO(config_content), f"{temp_dir}/test_config.ini")
        sftp.putfo(io.BytesIO(base64.b64decode(image_base64.split(',')[1])), f"{temp_dir}/test_image.jpg")

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
@app.post("/verify-scene/")
async def verify_scene_endpoint(body: VerifyBody):
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

# Pozostałe endpointy bez zmian...
@app.get("/", response_class=HTMLResponse)
async def root(req: Request):
    return templates.TemplateResponse("index.html", {"request": req})

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
