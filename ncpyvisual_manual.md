# NCPyVisual - Instrukcja obsługi
**Aplikacja webowa do konfiguracji i testowania fotoradarów**

---

## Spis treści

1. [Wstęp](#1-wstęp)
   - 1.1. [Opis aplikacji](#11-opis-aplikacji)
   - 1.2. [Uruchomienie](#12-uruchomienie)
   - 1.3. [Interfejs użytkownika](#13-interfejs-użytkownika)

2. [Import konfiguracji z terminala](#2-import-konfiguracji-z-terminala)
   - 2.1. [Połączenie z terminalem](#21-połączenie-z-terminalem)
   - 2.2. [Pobieranie konfiguracji](#22-pobieranie-konfiguracji)

3. [Galeria obrazów](#3-galeria-obrazów)
   - 3.1. [Pobieranie obrazów z terminala](#31-pobieranie-obrazów-z-terminala)
   - 3.2. [Dodawanie obrazów z dysku](#32-dodawanie-obrazów-z-dysku)
   - 3.3. [Zarządzanie galerią](#33-zarządzanie-galerią)

4. [Praca z obrazem roboczym](#4-praca-z-obrazem-roboczym)
   - 4.1. [Ustawianie obrazu roboczego](#41-ustawianie-obrazu-roboczego)
   - 4.2. [Nawigacja po obrazie](#42-nawigacja-po-obrazie)
   - 4.3. [Smart scaling](#43-smart-scaling)

5. [Tworzenie i edycja ROI](#5-tworzenie-i-edycja-roi)
   - 5.1. [Rysowanie ROI](#51-rysowanie-roi)
   - 5.2. [Edycja kształtu ROI](#52-edycja-kształtu-roi)
   - 5.3. [Parametry ROI](#53-parametry-roi)
   - 5.4. [Import ROI z XML](#54-import-roi-z-xml)

6. [Konfiguracja systemu](#6-konfiguracja-systemu)
   - 6.1. [Parametry podstawowe](#61-parametry-podstawowe)
   - 6.2. [Parametry zaawansowane](#62-parametry-zaawansowane)
   - 6.3. [Generowanie pakietu](#63-generowanie-pakietu)

7. [Weryfikacja i testowanie](#7-weryfikacja-i-testowanie)
   - 7.1. [NCSim - weryfikacja opcjonalna](#71-ncsim---weryfikacja-opcjonalna)
   - 7.2. [NCShot - przetwarzanie główne](#72-ncshot---przetwarzanie-główne)
   - 7.3. [Analiza wyników](#73-analiza-wyników)

8. [Panel wyników](#8-panel-wyników)
   - 8.1. [Tabela wyników](#81-tabela-wyników)
   - 8.2. [Obrazy płytek](#82-obrazy-płytek)
   - 8.3. [Statystyki](#83-statystyki)

9. [Rozwiązywanie problemów](#9-rozwiązywanie-problemów)
   - 9.1. [Najczęstsze problemy](#91-najczęstsze-problemy)
   - 9.2. [Debug i diagnostyka](#92-debug-i-diagnostyka)

---

## 1. Wstęp

### 1.1. Opis aplikacji

NCPyVisual to nowoczesna aplikacja webowa służąca do tworzenia, testowania i zarządzania konfiguracją fotoradarów. Aplikacja umożliwia:

- **Import konfiguracji** bezpośrednio z terminali przez SSH
- **Zarządzanie obrazami** z automatyczną konwersją formatów (.bif, .zur → .jpg)
- **Interaktywne tworzenie ROI** z inteligentnym skalowaniem
- **Weryfikację konfiguracji** za pomocą NCSim
- **Przetwarzanie obrazów** przez NCShot z analizą wyników
- **Generowanie pakietów** gotowych do wdrożenia

### 1.2. Uruchomienie

Aplikacja działa w przeglądarce internetowej. Aby ją uruchomić:

1. Uruchom serwer backend (FastAPI)
2. Otwórz przeglądarkę i przejdź pod adres aplikacji
3. Aplikacja automatycznie się załaduje

**Wymagania:**
- Nowoczesna przeglądarka (Chrome, Firefox, Safari, Edge)
- Połączenie z serwerem backend
- Dostęp do terminali (dla funkcji SSH)

### 1.3. Interfejs użytkownika

Interfejs składa się z następujących sekcji:

```
┌─────────────────────────────────────────────────────────┐
│                    Nagłówek aplikacji                   │
├──────────────┬─────────────────────────┬────────────────┤
│   Panel      │      Główny obszar      │                │
│   boczny     │        roboczy          │                │
│              │    (obraz + ROI)        │                │
│  • Import    │                         │                │
│  • Galeria   │                         │                │
│  • ROI       │                         │                │
│  • Config    │                         │                │
├──────────────┴─────────────────────────┴────────────────┤
│                Panel wyników NCShot                     │
│              (tabela + obrazy płytek)                   │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Import konfiguracji z terminala

### 2.1. Połączenie z terminalem

Aby połączyć się z terminalem fotoradaru:

1. **Wprowadź adres IP terminala** w polu "Adres IP terminala"
   - Format: `172.16.3.13`
   - Upewnij się, że terminal jest dostępny w sieci

2. **Podaj hasło root** (jeśli wymagane)
   - Pozostaw puste jeśli używasz kluczy SSH

3. **Kliknij "Pobierz konfigurację"**

### 2.2. Pobieranie konfiguracji

Po udanym połączeniu aplikacja automatycznie:

- **Pobierze parametry systemu:**
  - Numer seryjny
  - ID lokalizacji  
  - Współrzędne GPS
  - Adres backend
  - Maski sieciowe (SWD/Native Allow)

- **Zaimportuje konfigurację ROI:**
  - Wszystkie zdefiniowane ROI
  - Parametry każdego ROI
  - Automatyczne wyświetlenie na canvas

> **💡 Wskazówka:** ROI są natychmiast widoczne po imporcie, nawet bez obrazu roboczego. Zostaną automatycznie przeskalowane po ustawieniu obrazu.

---

## 3. Galeria obrazów

### 3.1. Pobieranie obrazów z terminala

1. **Ustaw ilość obrazów** do pobrania (1-50)
2. **Kliknij "🔥 Pobierz z terminala"**

Aplikacja automatycznie:
- Pobiera najnowsze obrazy z urządzenia
- **Konwertuje formaty** .bif i .zur na .jpg
- Dodaje obrazy do galerii z oznaczeniem źródła
- **Automatycznie ustawia pierwszy obraz** jako roboczy (jeśli brak obecnego)

**Obsługiwane formaty:**
- ✅ .jpg, .jpeg (natywnie)
- ✅ .bif, .zur (automatyczna konwersja)

### 3.2. Dodawanie obrazów z dysku

**Przeciągnij i upuść:**
- Przeciągnij pliki JPG/PNG na strefę drop
- Lub kliknij strefę i wybierz pliki

**Obsługiwane formaty z dysku:**
- .jpg, .jpeg, .png

### 3.3. Zarządzanie galerią

Każdy obraz w galerii ma:

**Oznaczenia źródła:**
- 🔗 **terminal** - pobrane z urządzenia
- 💾 **disk** - wczytane z dysku
- 🧪 **test** - obrazy testowe

**Kontrolki:**
- ☑️ **Zaznacz/Odznacz** - do przetwarzania przez NCShot
- 🖼️ **Kliknij miniaturę** - ustaw jako obraz roboczy  
- 🗑️ **Usuń** - usuwa obraz z galerii

**Akcje grupowe:**
- **Wyczyść wszystkie** - usuwa wszystkie obrazy
- **Zaznacz wszystkie** - zaznacza/odznacza wszystkie

---

## 4. Praca z obrazem roboczym

### 4.1. Ustawianie obrazu roboczego

**Obraz roboczy** to główny obraz wyświetlany w centrum aplikacji, na którym definiuje się ROI.

**Sposoby ustawiania:**
1. **Z galerii** - kliknij miniaturę obrazu
2. **Automatycznie** - pierwszy obraz z terminala
3. **Z dysku** - wczytaj przez "Wczytaj obraz"

### 4.2. Nawigacja po obrazie

**Kontrolki nawigacji:**
- 🔍+ **Powiększ** - zwiększa zoom
- 🔍- **Pomniejsz** - zmniejsza zoom  
- 🔎 **Dopasuj do okna** - automatyczne dopasowanie
- **1:1** - zoom 100%
- ⌖ **Wycentruj** - reset pozycji

**Kontrola myszą:**
- **Kółko myszy** - zoom in/out
- **Alt + przeciągnij** - przesuwanie obrazu
- **Prawy przycisk** - zakończ rysowanie ROI

### 4.3. Smart scaling

Aplikacja automatycznie skaluje:

**ROI scaling:**
- ROI zawsze przechowywane w **oryginalnej skali obrazu**
- Automatyczna konwersja przy zmianie obrazu roboczego
- **Zachowanie proporcji** niezależnie od rozmiaru wyświetlania

**Display scaling:**
- Dopasowanie do rozmiaru okna przeglądarki
- Zachowanie jakości obrazu
- Odpowiedni zoom dla pracy z ROI

---

## 5. Tworzenie i edycja ROI

### 5.1. Rysowanie ROI

1. **Kliknij "✏️ Rysuj ROI"**
2. **Klikaj punkty na obrazie** tworząc poligon
   - ⚠️ **WAŻNE:** Klikaj zgodnie z ruchem wskazówek zegara!
   - Minimum 3 punkty
3. **Prawy przycisk myszy** - zakończ i utwórz poligon

**Kolory ROI:**
- 🟢 Pierwszy ROI - zielony
- 🟡 Drugi ROI - żółty  
- 🟣 Trzeci ROI - magenta
- 🔵 Czwarty ROI - cyan
- 🟠 Piąty ROI - pomarańczowy

### 5.2. Edycja kształtu ROI

1. **Zaznacz ROI** (kliknij na poligon)
2. **Panel właściwości** pojawi się po prawej
3. **Kliknij "✏️ Edytuj kształt"**
4. **Przeciągaj punkty** aby zmienić kształt
5. **Kliknij "✅ Zatwierdź"** aby zakończyć

**Skróty klawiszowe:**
- **Delete/Backspace** - usuń zaznaczone ROI
- **F** - dopasuj ROI do obrazu
- **D** - debug ROI (informacje w konsoli)
- **R** - utwórz domyślne ROI

### 5.3. Parametry ROI

Po zaznaczeniu ROI w panelu właściwości można edytować:

**Parametry geometryczne:**
- **Kąt** - obrót tablicy (stopnie)
- **Zoom** - skala obrazu (np. 0.035 dla tablicy)
- **Offset H** - przesunięcie poziome refleksu
- **Offset V** - przesunięcie pionowe refleksu  
- **Skew H** - skoszenie poziome
- **Skew V** - skoszenie pionowe

**Wyznaczanie offsetów refleksu:**
1. Znajdź odbicie (reflex) tablicy na obrazie
2. Ctrl+Shift+Click na **lewy dolny róg refleksu** (punkt 0,0)
3. Ctrl+Shift+Click na **lewy dolny róg tablicy**
4. Aplikacja obliczy i wpisze offsety automatycznie

> **💡 Wskazówka:** Po wpisaniu wartości naciśnij Enter aby zatwierdzić zmiany.

### 5.4. Import ROI z XML

1. **Kliknij "📄 Wczytaj ROI z XML"**
2. **Wybierz plik .xml** z konfiguracją ROI
3. ROI zostaną automatycznie zaimportowane i wyświetlone

**Format XML:**
```xml
<roi id="ROI-1">
  <points>100,100;200,100;200,200;100,200</points>
  <angle>0</angle>
  <zoom>0.035</zoom>
  <reflexOffsetH>58</reflexOffsetH>
  <reflexOffsetV>-167</reflexOffsetV>
  <skewH>0</skewH>
  <skewV>0</skewV>
</roi>
```

---

## 6. Konfiguracja systemu

### 6.1. Parametry podstawowe

**Wymagane pola:**
- **Numer seryjny** - identyfikator urządzenia (np. 593-072-73194)
- **ID Lokalizacji** - kod lokalizacji (np. WSC.3.069) ⚠️ **WYMAGANE**
- **Szer. geogr.** - szerokość geograficzna (np. 51.2533333)
- **Dł. geogr.** - długość geograficzna (np. 22.5478611)

### 6.2. Parametry zaawansowane

**Sieć i komunikacja:**
- **Adres fotoradaru** - IP backend (np. 172.20.2.23)
- **SWD Allow** - maski sieci dla SWD (np. 172.16.0.0/24)
- **Native Allow** - maski dla native (domyślnie 0.0.0.0/0)

### 6.3. Generowanie pakietu

1. **Sprawdź wszystkie parametry** (szczególnie ID lokalizacji)
2. **Upewnij się że ROI są prawidłowe**
3. **Kliknij "📦 Generuj pakiet"**

**Pakiet zawiera:**
- Plik konfiguracyjny XML z ROI
- Wszystkie wymagane parametry systemu
- Gotowe do wgrania na urządzenie

---

## 7. Weryfikacja i testowanie

### 7.1. NCShot - przetwarzanie główne

**Cel:** Główne przetwarzanie obrazów z generowaniem wyników

1. **Zaznacz obrazy** w galerii do przetworzenia
2. **Upewnij się że ROI są zdefiniowane**
3. **Kliknij "🚀 Uruchom NCShot"**

**NCShot przetwarza:**
- Wszystkie zaznaczone obrazy z galerii
- Obraz roboczy (jeśli załadowany lokalnie)  
- Automatyczna konwersja formatów

### 7.3. Analiza wyników

Po zakończeniu NCShot:
- **Panel wyników** rozwija się automatycznie
- **Tabela** z detalami każdego rozpoznania
- **Obrazy płytek** jako miniatury
- **Statystyki** ogólne procesu

---

## 8. Panel wyników

### 8.1. Tabela wyników

**Kolumny tabeli:**
- **Obraz** - numer/nazwa źródłowego obrazu
- **Pojazd** - numer pojazdu na obrazie
- **Płytka** - rozpoznany numer rejestracyjny  
- **Kraj** - kod kraju tablicy
- **Poziom** - pewność rozpoznania (%)
- **Typ** - typ tablicy rejestracyjnej
- **Marka/Model/Kolor** - dane pojazdu
- **MMR Div.** - wartość rozbieżności wzorca
- **Obrazek płytki** - miniatura wyciętej płytki

**Kolorowanie wierszy:**
- 🟢 **Zielone** - wysoka pewność (>70%)
- 🟡 **Żółte** - średnia pewność (40-70%)  
- 🔴 **Czerwone** - niska pewność (<40%)

### 8.2. Obrazy płytek

**Miniatury płytek:**
- **Kliknij miniaturę** - powiększenie w modalu
- **Brak obrazu** - NCShot nie wygenerował miniatury
- **Obramowanie** wskazuje jakość rozpoznania

### 8.3. Statystyki

**Panel statystyk pokazuje:**
- **Przetworzonych obrazów** - łączna liczba
- **Obrazy z płytkami** - ile zawierało pojazdy
- **Rozpoznane płytki** - łączna liczba płytek
- **Płytki z obrazami** - ile ma wygenerowane miniatury
- **Sukces** - % obrazów z rozpoznaniami

**Kontrolki panelu:**
- **⬆️ Rozwiń / ⬇️ Zwiń** - pokaż/ukryj szczegóły

---

## 9. Rozwiązywanie problemów

### 9.1. Najczęstsze problemy

**🔌 Problemy z połączeniem SSH:**
```
Objaw: "Błąd połączenia z terminalem"
Rozwiązanie:
• Sprawdź adres IP terminala
• Sprawdź dostępność sieci (ping)
• Zweryfikuj hasło/klucze SSH
• Sprawdź firewalla
```

**🖼️ Problemy z obrazami:**
```
Objaw: "Nie można wczytać obrazu"
Rozwiązanie:
• Sprawdź format pliku (.jpg, .png)
• Sprawdź rozmiar pliku (<10MB)
• Odśwież przeglądarkę
• Wyczyść cache przeglądarki
```

**📐 Problemy z ROI:**
```
Objaw: "ROI w złym miejscu po zmianie obrazu"
Rozwiązanie:
• Sprawdź czy obraz ma właściwy rozmiar
• Użyj "Dopasuj do okna" w nawigacji
• Zresetuj zoom (1:1)
• Przeciągnij ROI na właściwe miejsce
```

**⚙️ Problemy z NCShot:**
```
Objaw: "NCShot nie działa"
Rozwiązanie:
• Sprawdź czy ROI są zdefiniowane
• Upewnij się że ID lokalizacji jest wypełnione
• Zaznacz przynajmniej jeden obraz
• Sprawdź logi serwera backend
```

### 9.2. Debug i diagnostyka

**🛠 Debug NCShot:**
1. **Kliknij "🛠 Debug NCShot"** 
2. **Sprawdź konsolę przeglądarki** (F12)
3. **Sprawdź informacje wyświetlone** w panelu

**🔍 Debug ROI:**
1. **Naciśnij klawisz "D"** na klawiaturze
2. **Sprawdź konsolę** - szczegóły skalowania ROI
3. **Sprawdź panel właściwości** - czy parametry są poprawne

**📋 Informacje systemowe:**
- **Rozmiar oryginalnego obrazu** - wymiary w pikselach
- **Skala wyświetlania** - współczynnik skalowania
- **Pozycja ROI** - współrzędne w oryginalnej skali
- **Status obrazów** - źródła i dostępność

**🌐 Sprawdzanie sieci:**
```bash
# Test połączenia z terminalem
ping 172.16.3.13

# Test SSH
ssh root@172.16.3.13

# Test portów backend
curl http://localhost:8000/health
```

---

## Wskazówki końcowe

### 💡 Najlepsze praktyki

1. **Zawsze rozpocznij od importu konfiguracji** z terminala
2. **Używaj obrazów o wysokiej rozdzielczości** dla lepszych wyników
3. **Testuj konfigurację na NCSim** przed wdrożeniem  
4. **Zapisuj kopie zapasowe** plików konfiguracyjnych
5. **Monitoruj statystyki rozpoznawania** w panelu wyników

### 🚀 Workflow pracy

```
1. Import konfiguracji z terminala
   ↓
2. Pobieranie obrazów z urządzenia  
   ↓
3. Ustawienie obrazu roboczego
   ↓ 
4. Dostosowanie/tworzenie ROI
   ↓
5. Weryfikacja przez NCSim (opcjonalnie)
   ↓
6. Przetwarzanie przez NCShot
   ↓
7. Analiza wyników
   ↓
8. Generowanie pakietu do wdrożenia
```

### 📞 Wsparcie

W przypadku problemów:
- Sprawdź sekcję rozwiązywania problemów
- Użyj funkcji debug w aplikacji
- Sprawdź logi serwera backend
- Skontaktuj się z działem technicznym

---

**© 2025 NCPyVisual - Aplikacja webowa do konfiguracji fotoradarów**
