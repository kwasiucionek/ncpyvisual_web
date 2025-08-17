#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test połączenia z NCShot - bazuje na twoich przykładach
"""
import http.client as httplib
import socket
import sys

def test_ncshot_basic_connection(host="192.168.122.228", port=5543):
    """Test podstawowego połączenia z NCShot"""
    print(f"🔍 Testowanie połączenia z NCShot: {host}:{port}")
    
    try:
        # Test 1: Podstawowe połączenie
        conn = httplib.HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/")
        resp = conn.getresponse()
        content = resp.read().decode('utf-8', 'ignore')
        
        print(f"✅ Status: {resp.status} {resp.reason}")
        print(f"📄 Odpowiedź: {content}")
        
        if resp.status == 200 and "NCShot OK" in content:
            print("✅ NCShot działa poprawnie!")
            return True
        else:
            print("❌ NCShot nie odpowiada prawidłowo")
            return False
            
    except socket.timeout:
        print("❌ Timeout - NCShot nie odpowiada w czasie")
        return False
    except ConnectionRefusedError:
        print("❌ Połączenie odrzucone - NCShot prawdopodobnie nie działa")
        return False
    except Exception as e:
        print(f"❌ Błąd połączenia: {e}")
        return False
    finally:
        try:
            conn.close()
        except:
            pass

def test_ncshot_config_list(host="192.168.122.228", port=5543):
    """Test listy dostępnych konfiguracji"""
    print(f"\n🔍 Sprawdzanie dostępnych konfiguracji...")
    
    try:
        conn = httplib.HTTPConnection(host, port, timeout=10)
        conn.request("GET", "/config")
        resp = conn.getresponse()
        content = resp.read().decode('utf-8', 'ignore')
        
        print(f"📋 Dostępne konfiguracje:")
        if content.strip():
            for config in content.strip().split('\n'):
                print(f"   - {config}")
        else:
            print("   Brak konfiguracji")
            
        return content.strip().split('\n') if content.strip() else []
        
    except Exception as e:
        print(f"❌ Błąd pobierania konfiguracji: {e}")
        return []
    finally:
        try:
            conn.close()
        except:
            pass

def test_simple_image_processing(host="192.168.122.228", port=5543):
    """Test z prostym obrazem JPEG (jak w reallysimpleclient.py)"""
    print(f"\n🔍 Test przetwarzania obrazu...")
    
    # Stwórz minimalny prawidłowy JPEG (1x1 piksel)
    minimal_jpeg = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x01, 0x00, 0x48, 0x00, 0x48, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x11, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0x02, 0x11, 0x01, 0x03, 0x11, 0x01,
        0xFF, 0xC4, 0x00, 0x14, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x08, 0xFF, 0xDA,
        0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0x2A, 0xFF, 0xD9
    ])
    
    try:
        # Próbuj z konfiguracją "default" (jeśli istnieje)
        conn = httplib.HTTPConnection(host, port, timeout=30)
        
        headers = {
            "Content-Type": "image/jpeg",
            "Content-Length": str(len(minimal_jpeg))
        }
        
        # Test z konfiguracją default
        conn.request("PUT", "/default?anpr=1&mmr=1", minimal_jpeg, headers)
        resp = conn.getresponse()
        content = resp.read().decode('utf-8', 'ignore')
        
        print(f"📊 Status: {resp.status} {resp.reason}")
        
        if resp.status == 200:
            print("✅ Obraz przetworzony pomyślnie!")
            token = resp.getheader("NCShot-Token")
            if token:
                print(f"🎫 Token: {token}")
                return token
            else:
                print("❌ Brak tokenu w odpowiedzi")
        elif resp.status == 404:
            print("❌ Konfiguracja 'default' nie istnieje")
        else:
            print(f"❌ Błąd przetwarzania: {content}")
            
        return None
        
    except Exception as e:
        print(f"❌ Błąd testu obrazu: {e}")
        return None
    finally:
        try:
            conn.close()
        except:
            pass

def main():
    """Główna funkcja testowa"""
    print("🚀 === TEST POŁĄCZENIA Z NCSHOT ===\n")
    
    # Sprawdź argumenty
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.122.228"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5543
    
    print(f"🎯 Testowanie: {host}:{port}")
    print("=" * 50)
    
    # Test 1: Podstawowe połączenie
    if not test_ncshot_basic_connection(host, port):
        print("\n❌ NCShot nie działa - sprawdź czy serwer jest uruchomiony")
        return False
    
    # Test 2: Lista konfiguracji
    configs = test_ncshot_config_list(host, port)
    
    # Test 3: Przetwarzanie obrazu
    token = test_simple_image_processing(host, port)
    
    print("\n" + "=" * 50)
    print("📋 PODSUMOWANIE:")
    print(f"✅ Połączenie: OK")
    print(f"📝 Konfiguracje: {len(configs)} dostępnych")
    print(f"🖼️ Przetwarzanie: {'OK' if token else 'BŁĄD'}")
    
    if configs:
        print(f"\n💡 ZALECENIE: Użyj jednej z istniejących konfiguracji:")
        for cfg in configs[:3]:  # Pokaż pierwsze 3
            print(f"   - {cfg}")
    
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print("Użycie: python test_ncshot_connection.py [host] [port]")
        print("Domyślnie: host=192.168.122.228, port=5543")
        sys.exit(0)
    
    main()
