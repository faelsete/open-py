"""
Open-PY — Entry Point
Uso: python3 -m open-py [start|doctor|status]
"""

import asyncio
import sys

from core.lifecycle import OpenPY


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "start"

    if command == "start":
        app = OpenPY()
        try:
            asyncio.run(app.run())
        except KeyboardInterrupt:
            print("\n👋 Open-PY encerrado pelo usuário")

    elif command == "doctor":
        from doctor.diagnostics import Doctor
        doctor = Doctor()
        report = asyncio.run(doctor.run_full_diagnostic(auto_repair=True))
        print(report.summary())

    elif command == "status":
        print("📊 Use o Telegram (/status) ou execute 'doctor' para diagnóstico")

    else:
        print(f"Comando desconhecido: {command}")
        print("Uso: python3 -m open-py [start|doctor|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
