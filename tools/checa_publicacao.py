#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confere se a página pública no ar é mesmo a que está no repositório.

    python3 tools/checa_publicacao.py [docs/index.html]

Existe por causa de 19/09/2026. A coleta rodou, o validador aprovou, o commit
foi para o repositório às 02:20 — e mesmo assim os leitores passaram a manhã
vendo a edição da véspera. O deploy do GitHub Pages falhou sozinho, num passo
que não é nosso:

    Error message: Failed to get ID Token.
    Request timeout: /32//idtoken/...

O build tinha funcionado; só a publicação não. Ninguém percebeu porque as duas
rotinas olhavam artifact e repositório, e davam o ciclo por encerrado ali. O
repositório estar certo não significa que o leitor esteja vendo o certo.

Este script fecha esse último metro: baixa a URL pública de verdade e compara
a edição que ela serve com a que está no arquivo local.

Saídas:
    0  a página no ar está em dia (ou adiante, logo após um deploy)
    1  a página no ar está ATRASADA — o deploy não aconteceu ou falhou
    2  não deu para verificar (rede, DNS, página fora do ar)

O código 2 é diferente de 1 de propósito: não conseguir olhar não é o mesmo
que olhar e encontrar problema.
"""

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

URL_PUBLICA = "https://wynb9t4n9w-png.github.io/Pauta-Thutor/"
TEMPO_LIMITE = 30


def baixar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PautaThutor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        saida = subprocess.run(
            ["curl", "-sS", "--max-time", str(TEMPO_LIMITE),
             "-H", "User-Agent: PautaThutor/1.0", url],
            capture_output=True, text=True,
        )
        if saida.returncode != 0 or not saida.stdout.strip():
            raise RuntimeError((saida.stderr or "resposta vazia").strip()[:200])
        return saida.stdout


def estado_de(html, origem):
    m = re.search(r"/\*DADOS\*/(.*?)/\*FIM\*/", html, re.S)
    if not m:
        raise RuntimeError("bloco /*DADOS*/ não encontrado em %s" % origem)
    return json.loads(m.group(1))


def resumo(estado):
    ed = (estado.get("edicoes") or [{}])[0]
    return {
        "atualizado_em": estado.get("atualizado_em") or "",
        "data": ed.get("data") or "",
        "itens": len(ed.get("itens") or []),
    }


def main():
    caminho = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/index.html")
    if not caminho.exists():
        print("FALHA: %s não existe. Rode a partir da raiz do repositório." % caminho)
        return 2

    try:
        local = resumo(estado_de(caminho.read_text(encoding="utf8"), str(caminho)))
    except Exception as e:
        print("FALHA: não consegui ler %s — %s" % (caminho, e))
        return 2

    try:
        no_ar = resumo(estado_de(baixar(URL_PUBLICA), URL_PUBLICA))
    except Exception as e:
        print("INDETERMINADO: não consegui baixar a página pública — %s" % e)
        print("  Não dá para afirmar que está em dia nem que está atrasada.")
        return 2

    print("repositório:  edição %s · %d itens · %s"
          % (local["data"], local["itens"], local["atualizado_em"]))
    print("no ar:        edição %s · %d itens · %s"
          % (no_ar["data"], no_ar["itens"], no_ar["atualizado_em"]))

    if no_ar["atualizado_em"] == local["atualizado_em"]:
        print("\nok  a página pública está servindo exatamente o que está no repositório.")
        return 0

    if no_ar["data"] > local["data"]:
        print("\nok  a página no ar está à frente do arquivo local — faça git pull antes de olhar.")
        return 0

    print("\nATRASADA: o commit está no repositório, mas o GitHub Pages ainda não publicou.")
    print("  O conteúdo está correto; o que falhou é o deploy, que é do GitHub.")
    print("  Confira as execuções de 'pages build and deployment' e mande rodar de novo")
    print("  a que falhou. Se o re-run ficar preso na fila, um commit novo no branch")
    print("  dispara um build limpo.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
