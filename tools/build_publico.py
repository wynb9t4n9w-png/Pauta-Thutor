#!/usr/bin/env python3
"""
Gera a versao publica do jornal Pauta Thutor a partir da pagina do artifact.

O artifact continua sendo a fonte da verdade: e la que a carteira de clientes
e a senha de administrador sao editadas. Esta versao publica e um espelho
somente-leitura, servido pelo GitHub Pages num endereco fixo.

O que e removido antes de publicar:
  - o bloco "auth" inteiro (usuario, salt e hash da senha);
  - os campos internos de cada cliente: query, excluir, revisar, razao, site;
  - a aba "Clientes" (painel administrativo).

Uso:
    python3 tools/build_publico.py <artifact.html> [docs/index.html]
"""

import json
import re
import sys
from pathlib import Path

# Campos de cliente que a renderizacao publica realmente usa.
# Conferido em renderJornal/renderQuinzena/renderArquivo: os demais campos
# aparecem apenas no painel administrativo, que nao vai para o ar.
CAMPOS_PUBLICOS = ("id", "nome", "setor", "uf", "ativo")

# Reset que o host do artifact injeta no <head>. Replicado aqui para que a
# pagina publica renderize identica a original.
RESET = (
    "<meta charset=utf8>"
    '<meta name=viewport content="width=device-width,initial-scale=1">'
    "<style>:root{color-scheme:light}"
    "body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif;"
    "background:#faf9f5;color:#141413}"
    "img{max-width:100%}"
    "[hidden]:not([hidden=until-found]){display:none!important}</style>"
)

DADOS_RE = re.compile(r"(/\*DADOS\*/)(.*?)(/\*FIM\*/)", re.S)
TAB_CLIENTES_RE = re.compile(r"[ \t]*<button[^>]*id=\"tab-clientes\"[^>]*>.*?</button>\s*\n?", re.S)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def conteudo_autoral(html: str) -> str:
    """Descarta o wrapper injetado pelo host e devolve so o conteudo da pagina."""
    marca = "<body>"
    i = html.find(marca)
    if i == -1:
        # Arquivo ja e o conteudo autoral puro.
        return html
    corpo = html[i + len(marca):]
    for fim in ("</body></html>", "</body>"):
        j = corpo.rfind(fim)
        if j != -1:
            corpo = corpo[:j]
            break
    return corpo.strip("\n")


def sanitiza(estado: dict) -> dict:
    """Remove segredos e plumbing interno do estado."""
    limpo = {k: v for k, v in estado.items() if k != "auth"}
    limpo["clientes"] = [
        {k: c[k] for k in CAMPOS_PUBLICOS if k in c}
        for c in estado.get("clientes", [])
    ]
    return limpo


def serializa(estado: dict) -> str:
    """JSON seguro para embutir dentro de <script>."""
    txt = json.dumps(estado, ensure_ascii=False, separators=(",", ":"))
    return txt.replace("</script", "<\\/script")


def build(origem: Path, destino: Path) -> dict:
    html = origem.read_text(encoding="utf8")
    corpo = conteudo_autoral(html)

    m = DADOS_RE.search(corpo)
    if not m:
        raise SystemExit(f"FALHA: bloco /*DADOS*/ nao encontrado em {origem}")

    estado = json.loads(m.group(2))
    limpo = sanitiza(estado)

    corpo = corpo[:m.start(2)] + serializa(limpo) + corpo[m.end(2):]

    corpo, n = TAB_CLIENTES_RE.subn("", corpo)
    if n == 0:
        raise SystemExit("FALHA: aba 'Clientes' nao encontrada — o layout mudou, revise o script.")

    titulo = TITLE_RE.search(corpo)
    titulo = titulo.group(1).strip() if titulo else "Pauta Thutor"

    pagina = (
        "<!doctype html>\n"
        '<html lang="pt-BR">\n<head>\n'
        f"{RESET}\n"
        '<meta name="robots" content="noindex,nofollow">\n'
        '<meta name="description" content="Clipping diario da carteira de clientes da consultoria Thutor.">\n'
        f"<meta property=\"og:title\" content=\"{titulo}\">\n"
        "</head>\n<body>\n"
        f"{corpo}\n"
        "</body>\n</html>\n"
    )

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina, encoding="utf8")

    edicoes = limpo.get("edicoes", [])
    return {
        "destino": str(destino),
        "bytes": len(pagina.encode("utf8")),
        "clientes": len(limpo.get("clientes", [])),
        "edicoes": len(edicoes),
        "ultima": edicoes[0].get("data") if edicoes else None,
        "itens": len(edicoes[0].get("itens", [])) if edicoes else 0,
        "atualizado_em": limpo.get("atualizado_em"),
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    origem = Path(sys.argv[1])
    destino = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("docs/index.html")
    info = build(origem, destino)
    print(f"ok  {info['destino']}  ({info['bytes']:,} bytes)")
    print(f"    edicao {info['ultima']} com {info['itens']} itens")
    print(f"    {info['clientes']} clientes · {info['edicoes']} edicoes no historico")
    print(f"    atualizado_em {info['atualizado_em']}")


if __name__ == "__main__":
    main()
