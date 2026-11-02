#!/usr/bin/env python3
"""THM Specter Tracker — Ponto de entrada compatível com o nome original do script.

Instala automaticamente as dependências necessárias (requests, playwright),
extrai o perfil público do TryHackMe (estatísticas, salas concluídas e badges),
salva em tryhackme_profile.json e envia o relatório em Embed para o Discord.
"""

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from src.main import main
except ModuleNotFoundError as exc:
    sys.stderr.write(
        f"[ERRO] Módulo interno não encontrado ({exc}). "
        f"Mantenha a pasta 'src/' junto a este arquivo (repositório completo) ou execute 'python main.py'.\n"
    )
    sys.exit(1)

if __name__ == "__main__":
    sys.exit(main())
