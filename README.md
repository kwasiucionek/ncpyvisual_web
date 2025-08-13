# NCPyVisual2 Web 📈

Aplikacja webowa do wizualnej konfiguracji systemów rozpoznawania tablic rejestracyjnych. Umożliwia zarządzanie regionami zainteresowania (ROI), import/eksport konfiguracji oraz weryfikację ustawień na terminalach.

## 🚀 Funkcjonalności

### Główne możliwości:
- **Import konfiguracji** - pobieranie ustawień bezpośrednio z terminali przez SSH
- **Wizualne rysowanie ROI** - interaktywne tworzenie i edycja regionów zainteresowania
- **Weryfikacja sceny** - testowanie konfiguracji na rzeczywistych zdjęciach z urządzenia
- **Generowanie pakietów** - eksport gotowych konfiguracji do plików ZIP
- **Podgląd zdjęć** - przeglądanie najnowszych zdjęć z terminali

### Obsługiwane formaty:
- Pliki obrazów: JPG, PNG
- Konfiguracje: XML, INI
- Archiwa: 7Z, ZIP
- Dane: PRN (pomiary)

## 🛠️ Instalacja

### Wymagania systemowe:
- Python 3.8+
- Dostęp SSH do jump host (10.10.33.113)
- Terminale z systemem NCShot

### Instalacja zależności:

```bash
pip install fastapi uvicorn pandas numpy paramiko py7zr jinja2 python-multipart
```

### Zmienne środowiskowe:

```bash
export JUMP_HOST_USER="twoj_login"
export JUMP_HOST_PASS="twoje_haslo"
```

## 🚀 Uruchomienie

### Tryb deweloperski:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Tryb produkcyjny:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Aplikacja będzie dostępna pod adresem: `http://localhost:8000`

## 📁 Struktura projektu

```
app/
├── main.py              # Główna aplikacja FastAPI
├── logic.py             # Logika przetwarzania danych
└── templates/
    └── index.html       # Interfejs użytkownika
```

### Kluczowe komponenty:

**Backend (FastAPI):**
- REST API endpoints
- Komunikacja SSH z terminalami
- Przetwarzanie plików konfiguracyjnych
- Generowanie pakietów

**Frontend (HTML + JavaScript):**
- Canvas z biblioteką Fabric.js
- Interaktywne rysowanie ROI
- Interfejs do zarządzania konfiguracją

## 🔌 API Endpoints

### Import i eksport
- `POST /import-from-device/` - Import konfiguracji z terminala
- `POST /generate-package/` - Generowanie pakietu konfiguracyjnego

### Zarządzanie obrazami
- `POST /fetch-device-images/` - Pobieranie zdjęć z urządzenia
- `POST /verify-scene/` - Weryfikacja konfiguracji ROI

### Struktura zapytań:

**Import z urządzenia:**
```json
{
  "ip": "172.16.3.13",
  "password": "haslo_root"
}
```

**Weryfikacja sceny:**
```json
{
  "package": {
    "rois": [...],
    "deployment": {...}
  },
  "password": "haslo",
  "terminal_ip": "172.16.3.13"
}
```

## 🎯 Instrukcja użytkowania

### 1. Import konfiguracji z terminala
1. Wprowadź adres IP terminala
2. Podaj hasło root (jeśli wymagane)
3. Kliknij "Pobierz konfigurację"

### 2. Praca z obrazami i ROI
1. Wczytaj obraz (lokalny plik lub z terminala)
2. Kliknij "Rysuj ROI" i zaznacz obszary na obrazie
3. Dostosuj parametry każdego ROI (kąt, zoom, offsety)
4. Zapisz konfigurację za pomocą prawego przycisku myszy

### 3. Konfiguracja parametrów
- **Numer seryjny** - identyfikator urządzenia
- **ID Lokalizacji** - kod lokalizacji (np. WSC.3.069)
- **Współrzędne GPS** - szerokość i długość geograficzna
- **Adres fotoradaru** - IP backend serwera
- **Maski dostępu** - konfiguracja sieci

### 4. Weryfikacja i eksport
1. Skonfiguruj wszystkie ROI
2. Kliknij "Weryfikuj scenę" dla testowania
3. Wygeneruj pakiet konfiguracyjny do pobrania

## ⚙️ Konfiguracja zaawansowana

### Parametry ROI:
- **Angle** - kąt obrotu regionu (stopnie)
- **Zoom** - powiększenie (1.0 = 100%)
- **Reflex Offset H/V** - przesunięcie odbicia (piksele)
- **Skew H/V** - zniekształcenie perspektywiczne

### Połączenie SSH:
Aplikacja korzysta z jump host do łączenia się z terminalami:
```
Laptop → Jump Host (10.10.33.113) → Terminal docelowy
```

### Struktura plików na terminalu:
- `/neurocar/etc/location.ini` - konfiguracja główna
- `/neurocar/etc/ncshot.d/[ID].ini` - konfiguracja ROI
- `/neurocar/data/deleted/` - archiwum zdjęć

## 🔧 Rozwiązywanie problemów

### Problemy z połączeniem SSH:
```bash
# Sprawdź dostępność jump host
ping 10.10.33.113

# Sprawdź zmienne środowiskowe
echo $JUMP_HOST_USER
echo $JUMP_HOST_PASS
```

### Błędy weryfikacji sceny:
- Upewnij się, że NCShot jest uruchomiony na terminalu
- Sprawdź czy w katalogu `/neurocar/data/deleted/` są pliki .7z
- Zweryfikuj konfigurację ROI

### Problemy z generowaniem pakietów:
- Sprawdź czy wszystkie wymagane pola są wypełnione
- Upewnij się, że przynajmniej jeden ROI jest zdefiniowany

## 📝 Logi i debugowanie

Aplikacja loguje działania do konsoli z poziomami:
- **INFO** - operacje normalne
- **WARNING** - ostrzeżenia
- **ERROR** - błędy krytyczne

Przykład włączenia szczegółowych logów:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🤝 Wsparcie

W przypadku problemów sprawdź:
1. Logi aplikacji w konsoli
2. Dostępność terminali przez SSH
3. Konfigurację zmiennych środowiskowych
4. Uprawnienia do katalogów na terminalach

## 📄 Licencja

Aplikacja przeznaczona do użytku wewnętrznego w systemach rozpoznawania tablic rejestracyjnych.
