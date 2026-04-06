"""
Open-PY v4.0 — Document Tools
Criação e leitura de PDF, CSV, XLSX.
"""

import csv
import io
import os
from typing import Optional


async def create_pdf(title: str, content: str, output_path: str) -> str:
    """Cria arquivo PDF com título e conteúdo de texto"""
    try:
        from fpdf import FPDF
    except ImportError:
        return '{"error": "fpdf2 não instalado. Execute: pip install fpdf2"}'

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Título
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, title, ln=True, align="C")
    pdf.ln(10)

    # Conteúdo
    pdf.set_font("Helvetica", "", 12)
    # Tratar quebras de linha
    for line in content.split("\n"):
        pdf.multi_cell(0, 7, line)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    pdf.output(output_path)
    return f"PDF criado: {output_path}"


async def read_pdf(path: str) -> str:
    """Lê e extrai texto de um arquivo PDF"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return '{"error": "PyMuPDF não instalado. Execute: pip install PyMuPDF"}'

    try:
        doc = fitz.open(path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        # Limitar tamanho para não estourar contexto
        if len(text) > 15000:
            text = text[:15000] + "\n\n[...texto truncado (muito longo)...]"
        return text
    except Exception as e:
        return f'{{"error": "Erro ao ler PDF: {e}"}}'


async def create_csv(data: str, output_path: str, delimiter: str = ",") -> str:
    """Cria arquivo CSV. Data deve ser JSON array de arrays ou array de objetos."""
    import json as _json
    try:
        parsed = _json.loads(data)
    except Exception:
        return '{"error": "data deve ser JSON válido (array de arrays ou objetos)"}'

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        if isinstance(parsed, list) and len(parsed) > 0:
            if isinstance(parsed[0], dict):
                writer = csv.DictWriter(f, fieldnames=parsed[0].keys(), delimiter=delimiter)
                writer.writeheader()
                writer.writerows(parsed)
            elif isinstance(parsed[0], list):
                writer = csv.writer(f, delimiter=delimiter)
                writer.writerows(parsed)
            else:
                return '{"error": "Formato não suportado"}'
        else:
            return '{"error": "data deve ser array não vazio"}'

    return f"CSV criado: {output_path}"


async def create_xlsx(data: str, output_path: str, sheet_name: str = "Sheet1") -> str:
    """Cria arquivo Excel XLSX. Data deve ser JSON array de arrays ou objetos."""
    try:
        from openpyxl import Workbook
    except ImportError:
        return '{"error": "openpyxl não instalado. Execute: pip install openpyxl"}'

    import json as _json
    try:
        parsed = _json.loads(data)
    except Exception:
        return '{"error": "data deve ser JSON válido"}'

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    if isinstance(parsed, list) and len(parsed) > 0:
        if isinstance(parsed[0], dict):
            # Header
            headers = list(parsed[0].keys())
            ws.append(headers)
            for row in parsed:
                ws.append([row.get(h, "") for h in headers])
        elif isinstance(parsed[0], list):
            for row in parsed:
                ws.append(row)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    wb.save(output_path)
    return f"XLSX criado: {output_path}"
