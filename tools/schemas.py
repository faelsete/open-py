"""
Open-PY v4.0 — Tool Schema Generator
Converte funções Python → OpenAI Function Calling JSON Schema.
Inspirado no padrão do Claude Code CLI.
"""

import inspect
from typing import get_type_hints, Any, Optional


# Mapa de tipos Python → JSON Schema types
PYTHON_TO_JSON_SCHEMA = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    list: {"type": "array"},
    dict: {"type": "object"},
    bytes: {"type": "string", "format": "binary"},
}


def python_type_to_schema(py_type) -> dict:
    """Converte tipo Python para JSON Schema type"""
    # Handle Optional[X]
    origin = getattr(py_type, "__origin__", None)
    if origin is type(None):
        return {"type": "null"}

    # Optional[str] → Union[str, None]
    args = getattr(py_type, "__args__", None)
    if args and type(None) in args:
        # Pegar o tipo real (não None)
        real_type = [a for a in args if a is not type(None)][0]
        return python_type_to_schema(real_type)

    # list[str] → {"type": "array", "items": {"type": "string"}}
    if origin is list and args:
        return {"type": "array", "items": python_type_to_schema(args[0])}

    # dict[str, Any] → {"type": "object"}
    if origin is dict:
        return {"type": "object"}

    # Tipos diretos
    return PYTHON_TO_JSON_SCHEMA.get(py_type, {"type": "string"})


def function_to_schema(func, name: str = None, description: str = None) -> dict:
    """
    Converte uma função Python para OpenAI Function Calling Schema.
    
    Exemplo de saída:
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Busca na web via DuckDuckGo",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termo de busca"},
                    "max_results": {"type": "integer", "description": "..."}
                },
                "required": ["query"]
            }
        }
    }
    """
    func_name = name or func.__name__
    func_doc = description or (func.__doc__ or "").strip().split("\n")[0]

    # Obter assinatura e type hints
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        # Pular self, cls
        if param_name in ("self", "cls"):
            continue

        # Tipo do parâmetro
        param_type = hints.get(param_name, str)
        schema = python_type_to_schema(param_type)

        # Descrição do parâmetro (extrair do docstring se possível)
        param_desc = _extract_param_doc(func.__doc__, param_name)
        if param_desc:
            schema["description"] = param_desc

        properties[param_name] = schema

        # Required: se não tem default
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "function",
        "function": {
            "name": func_name,
            "description": func_doc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }
    }


def _extract_param_doc(docstring: str, param_name: str) -> str:
    """Extrai descrição de parâmetro do docstring"""
    if not docstring:
        return ""
    for line in docstring.split("\n"):
        stripped = line.strip()
        # Formato: param_name: description ou param_name — description
        if stripped.startswith(f"{param_name}:") or stripped.startswith(f"{param_name} —"):
            return stripped.split(":", 1)[-1].strip() if ":" in stripped else stripped.split("—", 1)[-1].strip()
    return ""


def tools_to_schemas(tools: list) -> list[dict]:
    """
    Converte lista de Tool objects para schemas OpenAI.
    Usado pelo AgentBase para montar o parâmetro `tools` na chamada LLM.
    """
    schemas = []
    for tool in tools:
        schema = function_to_schema(
            func=tool.function,
            name=tool.name,
            description=tool.description,
        )
        schemas.append(schema)
    return schemas
