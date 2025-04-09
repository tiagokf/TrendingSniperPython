import sys
import os
from pathlib import Path

# Garante que o diretório 'src' esteja no caminho do Python
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / 'src'
sys.path.append(str(SRC_DIR))

from main import main

if __name__ == '__main__':
    main()
