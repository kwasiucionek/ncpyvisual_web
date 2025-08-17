#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sprawdzenie systemu NCShot - diagnoza std::bad_alloc
"""

import http.client as httplib
import paramiko
import os
import sys

def check_ncshot_system():
    """Kompleksowe sprawdzenie systemu NCShot"""
    print("🔍 === DIAGNOZA SYSTEMU NCSHOT ===")
    print("Sprawdzanie przyczyny std::bad_alloc\n")
    
    # KROK 1: Sprawdź konfigurację
    print("📋 KROK 1: Analiza konfiguracji tmp...")
    config_issues = check_config_content()
    
    # KROK 2: Sprawdź pliki na VM
    print("\n📁 KROK 2: Sprawdzanie plików systemowych na VM...")
    vm_issues = check_vm_system_files()
    
    # KROK 3: Sprawdź pamięć i procesy
    print("\n🖥️ KROK 3: Sprawdzanie zasobów VM...")
    resource_issues = check_vm_resources()
    
    # KROK 4: Podsumowanie i rozwiązania
    print("\n🔧 KROK 4: Diagnoza i rozwiązania...")
    provide_solutions(config_issues, vm_issues, resource_issues)

def check_config_content():
    """Sprawdź zawartość konfiguracji tmp"""
    issues = []
    
    try:
        conn = httplib.HTTPConnection("192.168.122.228", 5543, timeout=10)
        conn.request("GET", "/config/tmp")
        resp = conn.getresponse()
        content = resp.read().decode('utf-8', 'ignore')
        conn.close()
        
        if resp.status != 200:
            issues.append("Konfiguracja tmp niedostępna")
            return issues
            
        print(f"✅ Konfiguracja tmp pobrana ({len(content)} znaków)")
        
        # Sprawdź krytyczne sekcje
        critical_checks = {
            "neuronet.syntax.order": "Kolejność składni neuronowej",
            "syntax.folder = /neurocar/etc/syntax": "Ścieżka do składni", 
            "dta.file = /neurocar/etc/classreco77k-2016-07-29.dta": "Plik klasyfikatora",
            "[platerecognizer-main]": "Sekcja rozpoznawania płytek",
            "algorithms = neuronet.signature": "Algorytmy neuronowe"
        }
        
        print("🔍 Sprawdzanie krytycznych sekcji:")
        for check, description in critical_checks.items():
            if check in content:
                print(f"   ✅ {description}")
            else:
                print(f"   ❌ {description}")
                issues.append(f"Brak: {description}")
        
        # Wyciągnij ścieżki
        import re
        syntax_folder = re.search(r'syntax\.folder\s*=\s*([^\n]*)', content)
        dta_file = re.search(r'dta\.file\s*=\s*([^\n]*)', content)
        
        if syntax_folder:
            syntax_path = syntax_folder.group(1).strip()
            print(f"📂 Ścieżka składni: {syntax_path}")
        else:
            issues.append("Brak ścieżki do składni")
            
        if dta_file:
            dta_path = dta_file.group(1).strip()
            print(f"📄 Plik DTA: {dta_path}")
        else:
            issues.append("Brak ścieżki do pliku DTA")
            
        return issues
        
    except Exception as e:
        print(f"❌ Błąd sprawdzania konfiguracji: {e}")
        return ["Błąd połączenia z NCShot"]

def check_vm_system_files():
    """Sprawdź pliki systemowe na VM przez SSH"""
    issues = []
    
    VM_HOST = "192.168.122.228"
    VM_USER = os.getenv("VM_HOST_USER", "root")
    VM_PASS = os.getenv("VM_HOST_PASS")
    
    if not VM_PASS:
        print("❌ Brak VM_HOST_PASS")
        print("💡 Ustaw: export VM_HOST_PASS='hasło_do_vm'")
        return ["Brak dostępu SSH do VM"]
    
    try:
        print(f"🔗 Łączenie z VM: {VM_USER}@{VM_HOST}")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=15)
        
        print("✅ Połączono z VM")
        
        # KRYTYCZNE PLIKI dla NCShot
        critical_files = [
            ("/neurocar/etc/syntax/", "Folder składni neuronowej"),
            ("/neurocar/etc/classreco77k-2016-07-29.dta", "Klasyfikator pojazdów"),
            ("/neurocar/etc/", "Folder konfiguracji neurocar"),
        ]
        
        print("\n📁 Sprawdzanie krytycznych plików:")
        
        for file_path, description in critical_files:
            stdin, stdout, stderr = ssh.exec_command(f"ls -la {file_path}")
            output = stdout.read().decode('utf-8', 'ignore').strip()
            error = stderr.read().decode('utf-8', 'ignore').strip()
            
            if output and not error:
                print(f"   ✅ {description}: {file_path}")
                
                # Sprawdź zawartość folderu składni
                if "syntax" in file_path and file_path.endswith("/"):
                    stdin2, stdout2, stderr2 = ssh.exec_command(f"find {file_path} -name '*.bin' | head -10")
                    bin_files = stdout2.read().decode('utf-8', 'ignore').strip()
                    
                    if bin_files:
                        bin_count = len(bin_files.split('\n'))
                        print(f"      📄 Pliki .bin: {bin_count} znalezionych")
                        
                        # Pokaż pierwsze pliki
                        for bin_file in bin_files.split('\n')[:3]:
                            if bin_file.strip():
                                stdin3, stdout3, stderr3 = ssh.exec_command(f"ls -lh {bin_file.strip()}")
                                size_info = stdout3.read().decode('utf-8', 'ignore').strip()
                                if size_info:
                                    size = size_info.split()[4] if len(size_info.split()) > 4 else "?"
                                    print(f"         {os.path.basename(bin_file.strip())} ({size})")
                    else:
                        print(f"      ❌ BRAK plików .bin w {file_path}")
                        issues.append(f"Brak plików składni .bin w {file_path}")
                        
            else:
                print(f"   ❌ {description}: BRAK")
                issues.append(f"Brak pliku: {file_path}")
        
        # Sprawdź proces NCShot
        print(f"\n🔍 Sprawdzanie procesu NCShot:")
        stdin, stdout, stderr = ssh.exec_command("ps aux | grep ncshot | grep -v grep")
        process_output = stdout.read().decode('utf-8', 'ignore').strip()
        
        if process_output:
            print(f"   ✅ NCShot działa")
            for line in process_output.split('\n'):
                if 'ncshot' in line:
                    parts = line.split()
                    if len(parts) > 1:
                        cpu = parts[2] if len(parts) > 2 else "?"
                        mem = parts[3] if len(parts) > 3 else "?"
                        print(f"      PID: {parts[1]}, CPU: {cpu}%, MEM: {mem}%")
        else:
            print(f"   ❌ NCShot nie działa")
            issues.append("Proces NCShot nie działa")
        
        ssh.close()
        return issues
        
    except Exception as e:
        print(f"❌ Błąd SSH: {e}")
        return [f"Błąd SSH: {str(e)}"]

def check_vm_resources():
    """Sprawdź zasoby VM"""
    issues = []
    
    VM_HOST = "192.168.122.228"
    VM_USER = os.getenv("VM_HOST_USER", "root")
    VM_PASS = os.getenv("VM_HOST_PASS")
    
    if not VM_PASS:
        return ["Brak dostępu SSH do VM"]
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=10)
        
        # Sprawdź pamięć
        print("🖥️ Sprawdzanie zasobów:")
        
        stdin, stdout, stderr = ssh.exec_command("free -h")
        memory_output = stdout.read().decode('utf-8', 'ignore').strip()
        
        if memory_output:
            print("   📊 Pamięć:")
            for line in memory_output.split('\n'):
                if 'Mem:' in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        total = parts[1]
                        used = parts[2]
                        available = parts[6] if len(parts) > 6 else parts[3]
                        print(f"      Total: {total}, Used: {used}, Available: {available}")
                        
                        # Sprawdź czy available < 1GB
                        if 'M' in available or (available.replace('.', '').replace('G', '').isdigit() and float(available.replace('G', '')) < 1.0):
                            issues.append("Mało dostępnej pamięci (< 1GB)")
                            print(f"      ⚠️ Mało pamięci dostępnej!")
        
        # Sprawdź przestrzeń dyskową
        stdin, stdout, stderr = ssh.exec_command("df -h /neurocar")
        disk_output = stdout.read().decode('utf-8', 'ignore').strip()
        
        if disk_output:
            print("   💾 Przestrzeń dyskowa /neurocar:")
            for line in disk_output.split('\n')[1:]:  # Pomiń nagłówek
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 5:
                        used_percent = parts[4]
                        available = parts[3]
                        print(f"      Używane: {used_percent}, Dostępne: {available}")
                        
                        if used_percent.replace('%', '').isdigit() and int(used_percent.replace('%', '')) > 90:
                            issues.append("Mało miejsca na dysku (>90%)")
        
        ssh.close()
        return issues
        
    except Exception as e:
        print(f"❌ Błąd sprawdzania zasobów: {e}")
        return [f"Błąd zasobów: {str(e)}"]

def provide_solutions(config_issues, vm_issues, resource_issues):
    """Podaj rozwiązania na podstawie znalezionych problemów"""
    
    all_issues = config_issues + vm_issues + resource_issues
    
    print("📋 ZNALEZIONE PROBLEMY:")
    if not all_issues:
        print("✅ Nie znaleziono oczywistych problemów")
        print("🔍 Problem może być bardziej subtelny...")
    else:
        for i, issue in enumerate(all_issues, 1):
            print(f"   {i}. {issue}")
    
    print(f"\n🔧 ROZWIĄZANIA:")
    
    # Rozwiązania dla różnych typów problemów
    if any("składni" in issue or ".bin" in issue for issue in all_issues):
        print("""
1. PROBLEM Z PLIKAMI SKŁADNI (.bin):
   🔧 Rozwiązanie:
   a) Sprawdź czy istnieją pliki syntax/*.bin na VM
   b) Jeśli nie - skopiuj z innej instalacji NCShot
   c) Sprawdź uprawnienia: chmod -R 755 /neurocar/etc/syntax/
   d) Upewnij się że syntax.folder wskazuje na prawidłowy folder
""")

    if any("DTA" in issue or "classreco" in issue for issue in all_issues):
        print("""
2. PROBLEM Z KLASYFIKATOREM (.dta):
   🔧 Rozwiązanie:
   a) Sprawdź czy plik classreco77k-2016-07-29.dta istnieje
   b) Jeśli nie - skopiuj z backupu lub innej instalacji
   c) Sprawdź rozmiar pliku (powinien być >10MB)
   d) Sprawdź uprawnienia: chmod 644 /neurocar/etc/classreco77k-2016-07-29.dta
""")

    if any("pamięć" in issue.lower() or "bad_alloc" in issue for issue in all_issues):
        print("""
3. PROBLEM Z PAMIĘCIĄ (std::bad_alloc):
   🔧 Rozwiązanie:
   a) Zwiększ pamięć VM do minimum 4GB
   b) Restartuj NCShot: systemctl restart ncshot
   c) Sprawdź czy inne procesy nie zużywają pamięci
   d) Wyczyść cache: echo 3 > /proc/sys/vm/drop_caches
""")

    if any("neuronet.syntax.order" in issue for issue in all_issues):
        print("""
4. PROBLEM Z KONFIGURACJĄ NEURONET:
   🔧 Rozwiązanie:
   a) Sprawdź czy kolejność składni wskazuje na istniejące pliki
   b) Uprość syntax.order do: +omni(pl de gb) +pl(pl)
   c) Usuń nieistniejące składnie z konfiguracji
""")

    # Ogólne rozwiązanie
    print("""
🚀 SZYBKIE ROZWIĄZANIE DO TESTÓW:
1. Wyłącz MMR (używaj tylko ANPR):
   URL: /tmp?anpr=1&mmr=0

2. Uprość konfigurację - usuń algorithms=neuronet.signature

3. Użyj bardzo małego obrazu do testów (100x100px)

4. Sprawdź czy są inne instancje NCShot które mogą blokować pliki
""")

    print(f"\n💡 NASTĘPNE KROKI:")
    print("1. Uruchom: python ncshot_simple_test.py  # Test bez MMR")
    print("2. Sprawdź logi VM: tail -f /var/log/ncshot.log")
    print("3. Sprawdź procesy: ps aux | grep ncshot")
    print("4. W razie potrzeby zrestartuj NCShot")

def main():
    """Główna funkcja"""
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print("Diagnoza systemu NCShot - sprawdza przyczyny std::bad_alloc")
        print("Użycie: python ncshot_system_checker.py")
        print("\nZmienne środowiskowe:")
        print("VM_HOST_USER=root (lub inne)")
        print("VM_HOST_PASS=hasło_do_vm")
        return
    
    check_ncshot_system()

if __name__ == "__main__":
    main()
