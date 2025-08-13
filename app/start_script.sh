#!/bin/bash
# start.sh - SKRYPT STARTOWY NCPYVISUAL WEB

echo "🚀 Uruchamianie NCPyVisual Web..."

# Sprawdź czy istnieje plik .env
if [ ! -f ".env" ]; then
    echo "❌ Brak pliku .env! Kopiuję .env.example..."
    cp .env.example .env
    echo "✏️ Edytuj plik .env i uzupełnij JUMP_HOST_USER i JUMP_HOST_PASS"
    echo "📝 nano .env"
    exit 1
fi

# Sprawdź czy istnieje plik ncsim
if [ ! -f "bin/ncsim" ]; then
    echo "❌ Brak pliku bin/ncsim!"
    echo "📋 Skopiuj plik ncsim do katalogu bin/ i ustaw uprawnienia:"
    echo "   mkdir -p bin/"
    echo "   cp /path/to/ncsim bin/ncsim"
    echo "   chmod +x bin/ncsim"
    exit 1
fi

# Sprawdź zależności
echo "📦 Sprawdzam zależności..."
python3 -c "import fastapi, uvicorn, requests, paramiko" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Brakuje zależności! Instaluję..."
    pip3 install -r requirements.txt
fi

# Załaduj zmienne środowiskowe
export $(cat .env | grep -v '^#' | xargs)

# Sprawdź kluczowe zmienne
if [ -z "$JUMP_HOST_USER" ] || [ -z "$JUMP_HOST_PASS" ]; then
    echo "⚠️ UWAGA: Brak JUMP_HOST_USER lub JUMP_HOST_PASS w .env"
    echo "🔧 NCSim (SSH) nie będzie działać, ale NCShot (API) powinien funkcjonować"
fi

echo "✅ Wszystko gotowe!"
echo "🌐 Uruchamiam serwer na http://localhost:8000"
echo "📱 Otwórz przeglądarkę i przejdź do powyższego adresu"
echo ""
echo "🛑 Aby zatrzymać serwer, naciśnij Ctrl+C"
echo ""

# Uruchom serwer FastAPI
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --log-level info
