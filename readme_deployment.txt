# NCPyVisual Web - Instrukcje Wdrożenia

## 🎯 Architektura systemu (POPRAWIONA)

### **NCShot działa lokalnie na każdym terminalu** 📍
- **Stara implementacja (błędna)**: NCShot na `ntron01:5543` (centralny serwer)
- **Nowa implementacja (poprawna)**: NCShot na `terminal_ip:5543` (lokalnie)
- **Dostęp**: Przez **SSH tunnel** z jump host do terminala docelowego

### **Workflow komunikacji:**
```
[Aplikacja] → [Jump Host] → [SSH Tunnel] → [Terminal:5543/NCShot]
                                        → [Terminal:22/NCSim]
```

## ✅ Nowości w tej wersji

✅ **NCShot przez SSH tunnel** - komunikacja z NCShot na terminalu docelowym  
✅ **NCSim przez SSH exec** - uruchamianie w izolowanym środowisku  
✅ **Jednolity interfejs** - oba narzędzia używają tych samych danych SSH  
✅ **Szczegółowe wyniki** - obrazy tablic, dane pojazdów, informacje o tunelu  
✅ **Robust error handling** - lepsze błędy SSH i tuneli  

## 📋 Wymagania

- Python 3.8+
- **Jump Host**: `10.10.33.113` z credentials
- **Terminal docelowy**: z działającym NCShot na porcie 5543
- Plik binarny `ncsim` w katalogu `bin/`

## 🚀 Instalacja

### 1. Przygotuj środowisko

```bash
git clone <your-repo>
cd ncpyvisual_web
pip install -r requirements.txt
```

### 2. Konfiguracja SSH

```bash
cp .env.example .env
nano .env
```

**Kluczowe zmienne w `.env`:**
```bash
JUMP_HOST_USER=twoj_uzytkownik_jump_host
JUMP_HOST_PASS=twoje_haslo_jump_host
```

### 3. Dodaj plik ncsim

```bash
mkdir -p bin/
cp /path/to/ncsim bin/ncsim
chmod +x bin/ncsim
```

### 4. Uruchom aplikację

```bash
# Prosty sposób:
chmod +x start.sh
./start.sh

# LUB ręcznie:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Aplikacja: **http://localhost:8000**

## 🔧 Architektura techniczna

### **SSH Connections Flow:**

#### NCShot (przez SSH tunnel):
1. Połącz z jump host: `10.10.33.113`
2. Utwórz SSH tunnel: `localhost:random_port` → `terminal_ip:5543`
3. Wyślij HTTP requesty na `localhost:random_port`
4. NCShot odpowiada z pełnym XML + obrazy tablic
5. Zamknij tunnel i zwolnij token

#### NCSim (przez SSH exec):
1. Połącz z jump host: `10.10.33.113`
2. Połącz z terminalem: `terminal_ip:22`
3. Skopiuj pliki (ncsim, config, obraz, syntax)
4. Uruchom: `./ncsim -mconfig.ini image.jpg`
5. Pobierz wyniki i wyczyść katalog tymczasowy

## 🎮 Jak używać

### 1. **Podstawowy workflow:**
1. **Podaj IP terminala** (np. `172.16.3.13`) i hasło SSH
2. **Załaduj obraz** - przeciągnij JPG/PNG
3. **Narysuj ROI** - kliknij "Rysuj ROI", rysuj obszary, PPM kończy
4. **Ustaw parametry** - kliknij na ROI, dostosuj zoom/kąt/offsety
5. **Wybierz test:**
   - **🔬 NCSim** - symulacja przez SSH exec
   - **🎯 NCShot** - pełna analiza przez SSH tunnel

### 2. **Porównanie narzędzi:**

| **🎯 NCShot (Recommended)** | **🔬 NCSim (Alternative)** |
|----------------------------|---------------------------|
| ✅ Pełne wyniki XML         | 📊 Tylko procenty         |
| ✅ Obrazy tablic           | ❌ Brak obrazów           |
| ✅ Dane pojazdów MMR       | ❌ Tylko symulacja        |
| ✅ Timestamp, radar data   | ❌ Podstawowe info        |
| 🔗 SSH tunnel (port 5543) | 🔐 SSH exec (copy files)  |
| ⚡ ~5-8s                   | ⏱️ ~10-15s               |

### 3. **Interpretacja wyników:**

#### 🎯 NCShot - Pełna analiza:
```
📋 Tablice: tekst, kraj, pewność, pozycja, obrazy
🚗 Pojazdy: marka, model, kolor, prędkość, MMR confidence  
📡 Metadane: timestamp, parametry, dane radaru
🔗 SSH tunnel: localhost:port → terminal:5543
```

#### 🔬 NCSim - Symulacja:
```
✅ Recog-strong: 85.4% (siła rozpoznania)
☑️ Recog-weak: 67.2% (słabe rozpoznanie)  
⏱️ Czas: 3.2s
📂 Środowisko: /tmp/ncpyvisual_test_123456
```

## 🔍 Rozwiązywanie problemów

### **SSH Connection Issues:**

```bash
# Test jump host
ssh your_user@10.10.33.113

# Test terminal (przez jump host)
ssh -o ProxyJump=your_user@10.10.33.113 root@172.16.3.13

# Test NCShot na terminalu
ssh root@172.16.3.13  # przez jump
netstat -tlpn | grep :5543
curl -v http://localhost:5543/
```

### **NCShot nie odpowiada:**

```bash
# Na terminalu sprawdź:
systemctl status ncshot
journalctl -u ncshot -f

# Restart jeśli trzeba:
systemctl restart ncshot
```

### **SSH Tunnel problems:**

```python
# W logach aplikacji szukaj:
# "🔗 SSH tunnel utworzony: localhost:12345 -> 172.16.3.13:5543" 
# "✅ Tunnel działa, odpowiedź HTTP: 200"
# "❌ Test tunnel: Connection refused"
```

### **NCSim issues:**

```bash
# Sprawdź plik ncsim
ls -la bin/ncsim
file bin/ncsim  # powinno być: ELF 64-bit LSB executable

# Test ręczny na terminalu
ssh root@172.16.3.13
cd /tmp && /path/to/ncsim -mconfig.ini test.jpg
```

### **ROI Problems:**
- **ROI nie zapisuje się**: sprawdź czy obraz jest załadowany
- **Błędne współrzędne**: ROI są względne (0-1), automatycznie konwertowane na piksele
- **Brak wyników**: sprawdź parametry zoom (>0) i angle

## 📚 API Endpoints

```python
POST /verify-scene/         # NCSim (SSH exec)
POST /verify-scene-ncshot/  # NCShot (SSH tunnel)  
POST /generate-package/     # Generowanie pakietu INI
POST /import-from-device/   # Import z terminala (TODO)
POST /fetch-device-images/  # Pobieranie zdjęć (TODO)
```

## 🔄 Różnice vs stara aplikacja

| **Stara aplikacja (wxPython)** | **Nowa aplikacja (Web)** |
|-------------------------------|--------------------------|
| `startNcshot()` → `ntron01:5543` | `verify_roi_with_ncshot()` → `terminal:5543` |
| HTTP direct connection | SSH tunnel connection |
| `startNcsim()` → terminal exec | `verify_roi_with_ncsim()` → isolated env |
| XML config files | INI config files |
| Local GUI | Web interface |

## 📝 Zmienne środowiskowe

```bash
# Wymagane (dla SSH):
JUMP_HOST_USER=username        # User na jump host
JUMP_HOST_PASS=password        # Hasło jump host

# Opcjonalne:
LOG_LEVEL=INFO                 # DEBUG dla więcej logów
NCSHOT_TIMEOUT=30              # Timeout HTTP dla NCShot
```

## 🛠️ Development & Debugging

### **Włącz szczegółowe logi:**
```bash
export LOG_LEVEL=DEBUG
uvicorn app.main:app --log-level debug --reload
```

### **Monitoruj requesty SSH:**
```python
# W kodzie app/main.py znajdziesz logi:
logging.info("🔗 SSH tunnel utworzony...")
logging.info("📤 Wysyłam konfigurację do...")  
logging.info("✅ Otrzymano wynik...")
```

### **Test manual SSH tunnel:**
```bash
# Ręczny test tunelu:
ssh -L 12345:172.16.3.13:5543 user@10.10.33.113
curl http://localhost:12345/  # w drugim terminalu
```

### **Struktura projektu:**
```
app/
├── main.py          # FastAPI + SSH tunnel logic
├── logic.py         # Parsowanie XML/text results  
└── templates/
    └── index.html   # Frontend z dual buttons

bin/
└── ncsim           # Binary executable

requirements.txt    # Python dependencies
.env               # SSH credentials (nie commitować!)
```

## 🆘 Kontakt / Support

**Typowe problemy:**

1. **"Brak JUMP_HOST_USER/JUMP_HOST_PASS"** → Sprawdź `.env`
2. **"Connection refused"** → Sprawdź dostępność terminala/jump host
3. **"NCShot timeout"** → Terminal może być przeciążony lub NCShot nie działa
4. **"SSH tunnel failed"** → Sprawdź czy port 5543 jest dostępny na terminalu

**Debug workflow:**
1. Sprawdź logi FastAPI (`uvicorn --log-level debug`)
2. Sprawdź konsolę przeglądarki (F12)
3. Test SSH connection ręcznie
4. Sprawdź status NCShot na terminalu

---
**🔑 Kluczowa zmiana**: NCShot działa **lokalnie na każdym terminalu**, nie centralnie. Komunikacja przez **SSH tunnel** zapewnia bezpieczny dostęp przez jump host.
