# config.py - Konfiguracja dla maszyny wirtualnej
VM_HOST = "192.168.122.228"
VM_USER = os.getenv("VM_HOST_USER", "kwasiucionek")  # lub jak w JUMP_HOST_USER
VM_PASS = os.getenv("VM_HOST_PASS", "rooNg2Ph")  # lub jak w JUMP_HOST_PASS

# Konfiguracja ncshot
NCSHOT_HOST = VM_HOST
NCSHOT_PORT = 5543

# Inne zmienne z starej aplikacji
temps_to_remove = ["tmp.ini", "temp.jpg", "conf.xml"]

general_params = ["reflexOffsetH", "reflexOffsetV", "anisotropy", "minProbability", "candidates", "autolevel"]

default_values = {"anisotropy": 1.0, "minProbability": 0.69, "candidates": 5, "autolevel": 5}

branch_params = ["angle", "zoom", "skewV", "skewH"]

typeInt = ["reflexOffsetH", "reflexOffsetV", "candidates", "autolevel"]
