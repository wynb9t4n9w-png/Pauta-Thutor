#!/usr/bin/env python3
"""
Testa a página pública num navegador de verdade, clicando em cada aba.

Existe por causa de um erro real: ao remover a aba administrativa "Clientes",
a versão pública passou a quebrar nas abas "15 dias" e "Arquivo". A função
irPara() percorre a lista de abas e chama el("tab-"+k).setAttribute(...);
sem o botão tab-clientes esse el() devolve null, a função estoura no meio e o
painel aparece — porém vazio. Um teste que só olhava o painel do Jornal não
pegou isso.

Este teste clica em cada aba e confere que o painel correspondente ficou
visível, com conteúdo, e sem nenhum erro de JavaScript na página.

Uso:
    python3 tools/teste_pagina.py [docs/index.html]
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ABAS = ("jornal", "quinzena", "arquivo")
CONTEUDO_MINIMO = 200  # bytes de innerHTML; um painel vazio fica perto de zero

SONDA = """
<script>
window.__erros = [];
window.addEventListener("error", function(e){ window.__erros.push(String(e.message)); });
window.addEventListener("load", function(){
  setTimeout(function(){
    var linhas = [];
    ["jornal","quinzena","arquivo"].forEach(function(k){
      var b = document.getElementById("tab-" + k);
      if (b) { try { b.click(); } catch (e) { window.__erros.push("click " + k + ": " + e.message); } }
      var p = document.getElementById("p-" + k);
      linhas.push([
        k,
        b ? "botao-ok" : "SEM-BOTAO",
        p ? (p.hidden ? "OCULTO" : "visivel") : "SEM-PAINEL",
        p ? p.innerHTML.length : -1
      ].join(","));
    });
    var d = document.createElement("div");
    d.id = "__sonda";
    d.textContent = linhas.join(";") + "|" + (window.__erros.join(" ~ ") || "nenhum");
    document.body.appendChild(d);
  }, 150);
});
</script>
"""


def acha_chromium() -> str | None:
    for padrao in ("chromium*/chrome-linux/chrome", "chromium*/chrome-linux/headless_shell"):
        for c in sorted(Path("/opt/pw-browsers").glob(padrao)):
            return str(c)
    return None


def main() -> None:
    pagina = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "docs" / "index.html"
    if not pagina.exists():
        raise SystemExit(f"FALHA: {pagina} não existe. Rode tools/build_publico.py antes.")

    chrome = acha_chromium()
    if not chrome:
        print("aviso: Chromium não encontrado; teste de navegador pulado.")
        return

    html = pagina.read_text(encoding="utf8")
    with tempfile.TemporaryDirectory() as tmp:
        alvo = Path(tmp) / "sonda.html"
        alvo.write_text(html.replace("</body>", SONDA + "</body>"), encoding="utf8")

        r = subprocess.run(
            [chrome, "--headless", "--no-sandbox", "--disable-gpu",
             "--virtual-time-budget=8000", "--dump-dom", alvo.as_uri()],
            capture_output=True, text=True,
        )

    m = re.search(r'id="__sonda"[^>]*>(.*?)</div>', r.stdout, re.S)
    if not m:
        raise SystemExit(
            "FALHA: a sonda não rodou — a página provavelmente quebrou antes de carregar.\n"
            + r.stdout[-600:]
        )

    corpo, erros = m.group(1).split("|", 1)
    falhou = 0

    for linha in corpo.split(";"):
        aba, botao, visivel, tamanho = linha.split(",")
        tamanho = int(tamanho)
        problemas = []
        if botao != "botao-ok":
            problemas.append("botão da aba não existe")
        if visivel != "visivel":
            problemas.append(f"painel {visivel.lower()} depois do clique")
        if tamanho < CONTEUDO_MINIMO:
            problemas.append(f"painel praticamente vazio ({tamanho} bytes)")

        falhou += bool(problemas)
        marca = "ok  " if not problemas else "FALHOU"
        print(f"{marca} aba {aba:<9} {tamanho:>6} bytes de conteúdo"
              + ("  <<< " + "; ".join(problemas) if problemas else ""))

    if erros.strip() != "nenhum":
        falhou += 1
        print(f"FALHOU erros de JavaScript na página: {erros.strip()}")

    print()
    if falhou:
        print(f"{falhou} problema(s). A página pública não está pronta para publicar.")
        raise SystemExit(1)
    print(f"{len(ABAS)} de {len(ABAS)} abas funcionando, sem erro de JavaScript.")


if __name__ == "__main__":
    main()
