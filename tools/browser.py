"""
Open-PY v4.0 — Browser Tools
Automação de navegador via Playwright.
Permite navegar, clicar, digitar, capturar screenshots.
"""

import asyncio
import os
from typing import Optional

from shared.logger import get_logger

log = get_logger("browser-tools")

# Instância global do browser (reutilizada entre chamadas)
_browser = None
_page = None


async def _get_page():
    """Obtém ou cria instância do browser + página"""
    global _browser, _page

    if _page and not _page.is_closed():
        return _page

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright não instalado. Execute:\n"
            "pip install playwright && playwright install chromium"
        )

    pw = await async_playwright().start()
    _browser = await pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"]
    )
    _page = await _browser.new_page()
    _page.set_default_timeout(15000)  # 15s timeout
    return _page


async def browser_navigate(url: str) -> str:
    """Navega para uma URL e retorna o título da página"""
    page = await _get_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded")
        title = await page.title()
        status = response.status if response else "unknown"
        return f"Navegou para: {url}\nTítulo: {title}\nStatus: {status}"
    except Exception as e:
        return f'{{"error": "Falha ao navegar: {e}"}}'


async def browser_click(selector: str) -> str:
    """Clica em um elemento da página usando CSS selector"""
    page = await _get_page()
    try:
        await page.click(selector, timeout=10000)
        return f"Clicou em: {selector}"
    except Exception as e:
        return f'{{"error": "Falha ao clicar em {selector}: {e}"}}'


async def browser_type(selector: str, text: str) -> str:
    """Digita texto em um campo de input usando CSS selector"""
    page = await _get_page()
    try:
        await page.fill(selector, text, timeout=10000)
        return f"Digitou '{text[:50]}...' em: {selector}"
    except Exception as e:
        return f'{{"error": "Falha ao digitar em {selector}: {e}"}}'


async def browser_screenshot(output_path: str = "/tmp/open-py/screenshot.png") -> str:
    """Captura screenshot da página atual"""
    page = await _get_page()
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        await page.screenshot(path=output_path, full_page=False)
        return f"Screenshot salvo: {output_path}"
    except Exception as e:
        return f'{{"error": "Falha no screenshot: {e}"}}'


async def browser_get_text(selector: str = "body") -> str:
    """Extrai texto visível de um elemento da página"""
    page = await _get_page()
    try:
        text = await page.inner_text(selector, timeout=10000)
        # Limitar tamanho
        if len(text) > 10000:
            text = text[:10000] + "\n\n[...texto truncado...]"
        return text
    except Exception as e:
        return f'{{"error": "Falha ao extrair texto: {e}"}}'


async def browser_get_html(selector: str = "body") -> str:
    """Extrai HTML interno de um elemento da página"""
    page = await _get_page()
    try:
        html = await page.inner_html(selector, timeout=10000)
        if len(html) > 10000:
            html = html[:10000] + "\n<!-- truncado -->"
        return html
    except Exception as e:
        return f'{{"error": "Falha ao extrair HTML: {e}"}}'


async def browser_execute_js(code: str) -> str:
    """Executa JavaScript na página e retorna resultado"""
    page = await _get_page()
    try:
        result = await page.evaluate(code)
        return str(result)
    except Exception as e:
        return f'{{"error": "Falha no JS: {e}"}}'


async def browser_wait(selector: str, timeout: int = 10000) -> str:
    """Aguarda um elemento aparecer na página"""
    page = await _get_page()
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        return f"Elemento encontrado: {selector}"
    except Exception as e:
        return f'{{"error": "Timeout esperando {selector}: {e}"}}'


async def browser_close() -> str:
    """Fecha o navegador"""
    global _browser, _page
    try:
        if _page:
            await _page.close()
        if _browser:
            await _browser.close()
        _page = None
        _browser = None
        return "Navegador fechado"
    except Exception as e:
        return f'{{"error": "Falha ao fechar: {e}"}}'
