#!/usr/bin/env python3
"""
Monta o dossiê de fontes produtivas a partir do histórico do jornal.

A lista de veículos do prompt é fixa e genérica. Este script olha o que de
fato aconteceu: quais veículos já renderam notícia de quais clientes, nas
edições guardadas no estado. Isso vira uma camada extra de busca, dirigida
por evidência em vez de suposição — e melhora sozinha conforme os dias passam.

O dossiê é ADITIVO. Ele nunca substitui as camadas (a) e (b) do PASSO 2 nem
vira filtro de domínio: cliente sem histórico continua coberto pela busca
aberta, e um veículo que parou de publicar sai sozinho da lista quando as
edições antigas saem da janela.

Uso:
    python3 tools/fontes.py <estado.html|estado.json> [--min-dias N]
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

# Um par cliente×veículo entra no dossiê a partir de UMA aparição: com poucos
# dias de histórico, exigir repetição descartaria quase tudo. O ruído é barato
# (uma busca a mais), o falso negativo é caro (uma notícia perdida).
MIN_APARICOES = 1


def carrega(caminho: Path) -> dict:
    txt = caminho.read_text(encoding="utf8")
    if caminho.suffix.lower() == ".json":
        return json.loads(txt)
    m = re.search(r"/\*DADOS\*/(.*?)/\*FIM\*/", txt, re.S)
    if not m:
        raise SystemExit(f"FALHA: bloco /*DADOS*/ não encontrado em {caminho}")
    return json.loads(m.group(1))


def dossie(estado: dict) -> dict:
    nomes = {c.get("id"): c.get("nome", c.get("id")) for c in estado.get("clientes", [])}
    ativos = {c.get("id") for c in estado.get("clientes", []) if c.get("ativo") is not False}

    por_cliente: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    ultima: dict[tuple[str, str], str] = {}
    global_: dict[str, int] = defaultdict(int)
    # Dominio de cada veiculo, extraido das URLs publicadas. E o que permite
    # ler o veiculo direto (WebFetch) ou restringir uma busca a ele.
    dominios: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    edicoes = estado.get("edicoes", [])

    for ed in edicoes:
        data = ed.get("data", "")
        for it in ed.get("itens", []):
            cid, fonte = it.get("cliente_id"), (it.get("fonte") or "").strip()
            if not cid or not fonte:
                continue
            por_cliente[cid][fonte] += 1
            global_[fonte] += 1
            chave = (cid, fonte)
            if chave not in ultima or data > ultima[chave]:
                ultima[chave] = data
            host = urlparse(it.get("url") or "").netloc.lower().removeprefix("www.")
            if host:
                dominios[fonte][host] += 1

    linhas = []
    for cid in sorted(por_cliente, key=lambda c: -sum(por_cliente[c].values())):
        if cid not in ativos:
            continue
        fontes = [(f, n) for f, n in por_cliente[cid].items() if n >= MIN_APARICOES]
        if not fontes:
            continue
        fontes.sort(key=lambda x: (-x[1], x[0]))
        desc = ", ".join(
            f"{f} [{_dominio(dominios[f])}] ({n}x, últ. {ultima[(cid, f)]})" for f, n in fontes
        )
        linhas.append(f"{cid} — {nomes.get(cid, cid)}: {desc}")

    sem_historico = sorted(
        nomes[c] for c in ativos if c not in por_cliente and c in nomes
    )

    return {
        "linhas": linhas,
        "global": sorted(global_.items(), key=lambda x: (-x[1], x[0])),
        "dominios": {f: _dominio(d) for f, d in dominios.items()},
        "sem_historico": sem_historico,
        "edicoes": len(edicoes),
        "periodo": (edicoes[-1].get("data"), edicoes[0].get("data")) if edicoes else (None, None),
        "itens": sum(global_.values()),
        "ativos": len(ativos),
    }


def _dominio(contagem: dict[str, int]) -> str:
    """O host mais frequente daquele veiculo; '?' se nenhuma URL foi parseavel."""
    if not contagem:
        return "?"
    return max(contagem.items(), key=lambda x: x[1])[0]


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    d = dossie(carrega(Path(sys.argv[1])))

    if not d["linhas"]:
        print("DOSSIÊ DE FONTES: sem histórico ainda. Use apenas as camadas (a) e (b).")
        return

    ini, fim = d["periodo"]
    print("=== DOSSIÊ DE FONTES PRODUTIVAS ===")
    print(f"Base: {d['edicoes']} edições ({ini} a {fim}), {d['itens']} itens.")
    print()
    print("Veículos que JÁ renderam notícia de cada cliente. Para cada linha,")
    print("faça uma busca adicional combinando o nome do cliente com esses")
    print("veículos. É a camada (c) do PASSO 2 — ADITIVA, nunca substitui as")
    print("outras e nunca vira allowed_domains.")
    print()
    for l in d["linhas"]:
        print(f"  {l}")
    print()
    print("--- veículos mais produtivos no geral, com domínio ---")
    print("Com WebFetch liberado, leia a listagem de notícias destes domínios direto.")
    print("Com WebFetch bloqueado, use o domínio em allowed_domains numa busca dirigida.")
    for f, n in d["global"][:15]:
        print(f"  {n:3d}  {f}  →  {d['dominios'].get(f, '?')}")
    if d["sem_historico"]:
        print()
        print(f"--- {len(d['sem_historico'])} clientes ativos ainda sem histórico ---")
        print("Estes dependem só das camadas (a) e (b); não os deixe de fora.")
        print("  " + "; ".join(d["sem_historico"]))


if __name__ == "__main__":
    main()
