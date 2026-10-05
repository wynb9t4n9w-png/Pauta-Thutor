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

Há uma segunda parte, CURADA: fontes/complementares.json. O histórico só
ensina sobre quem já apareceu; cliente que nunca sai no jornal não deixa
rastro nenhum. Para esses, o registro guarda à mão as salas de imprensa sem
feed, os veículos regionais e setoriais que já os cobriram, buscas extras e
os nomes dos executivos — e o dossiê imprime tudo junto, para as camadas
(a), (d) e a segunda passada.

Uso:
    python3 tools/fontes.py <estado.html|estado.json>
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

COMPLEMENTARES = Path(__file__).resolve().parent.parent / "fontes" / "complementares.json"
FEEDS = Path(__file__).resolve().parent.parent / "fontes" / "feeds.json"

# Um veículo sem feed entra na lista de leitura a partir de três notícias no
# histórico: abaixo disso, a lista enche de portais que renderam por acaso.
MIN_LEITURA = 3
# Portais nacionais de alto volume: a página inicial não mostra notícia de um
# cliente específico, e a camada (b) já os cobre por busca.
GRANDE_IMPRENSA = {
    "infomoney.com.br", "exame.com", "valor.globo.com", "folha.uol.com.br", "estadao.com.br",
    "oglobo.globo.com", "g1.globo.com", "cnnbrasil.com.br", "istoedinheiro.com.br",
    "braziljournal.com", "neofeed.com.br", "poder360.com.br", "bloomberglinea.com.br",
}


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


def complementares(estado: dict, caminho: Path = COMPLEMENTARES) -> list[str]:
    """Linhas do registro curado, só para clientes ativos, na ordem da carteira."""
    if not caminho.exists():
        return []
    reg = json.loads(caminho.read_text(encoding="utf8")).get("clientes", {})
    linhas = []
    for c in estado.get("clientes", []):
        cid = c.get("id")
        r = reg.get(cid)
        if not r or c.get("ativo") is False:
            continue
        linhas.append(f"{cid} — {c.get('nome', cid)}")
        if r.get("nota"):
            linhas.append(f"    nota: {r['nota']}")
        for pg in r.get("paginas", []):
            linhas.append(f"    ler (d): {pg.get('nome', '')} [{pg.get('tipo', '')}] → {pg['url']}")
        for b in r.get("buscas", []):
            linhas.append(f"    buscar (a): {b}")
        pessoas = [f"{p['nome']} ({p['cargo']})" for p in r.get("pessoas", [])]
        if pessoas:
            linhas.append(f"    pessoas (rodada 2): {'; '.join(pessoas)}")
    return linhas


def _host(url: str) -> str:
    return urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")


def leitura(estado: dict, feeds: Path = FEEDS, extras: Path = COMPLEMENTARES) -> list[dict]:
    """A lista fechada da camada (d): o que ler direto, sem gastar busca.

    Nasceu em 05/10/2026. Com o teto de 200 buscas por sessão, a coleta passou a
    gastar tudo pesquisando e a leitura direta — que em setembro rendia de 12 a 29
    itens por noite — caiu para 0 a 4. CCEE (14 itens em 15 edições) e Sesc DF
    (13) sumiram do jornal: os dois não têm feed, e ninguém mais abria a página.
    WebFetch não gasta busca. Por isso a lista é explícita e vai inteira.

    Junta, sem repetir domínio e deixando de fora o que a camada (e) já lê:
      1. o site de cada cliente ativo;
      2. as páginas de fontes/complementares.json;
      3. os veículos sem feed que renderam pelo menos MIN_LEITURA notícias.
    """
    cobertos = set()
    if feeds.exists():
        cobertos = {_host(f["url"]) for f in json.loads(feeds.read_text(encoding="utf8")).get("feeds", [])}
    ativos = [c for c in estado.get("clientes", []) if c.get("ativo") is not False]
    nomes = {c["id"]: c.get("nome", c["id"]) for c in ativos}
    lista: dict[str, dict] = {}

    def poe(url, cid, motivo):
        h = _host(url)
        if not h or h in cobertos:
            return
        u = url if "://" in url else "https://" + url
        chave = (h + urlparse(u).path).rstrip("/")
        if chave not in lista:
            lista[chave] = {"url": u, "clientes": [], "motivo": motivo}
        if cid and nomes.get(cid) and nomes[cid] not in lista[chave]["clientes"]:
            lista[chave]["clientes"].append(nomes[cid])

    for c in ativos:
        if c.get("site"):
            poe(c["site"], c["id"], "site do cliente")
    if extras.exists():
        reg = json.loads(extras.read_text(encoding="utf8")).get("clientes", {})
        for cid, r in reg.items():
            if cid in nomes:
                for pg in r.get("paginas", []):
                    poe(pg["url"], cid, pg.get("tipo") or "fonte complementar")

    contagem: dict[str, int] = defaultdict(int)
    quem: dict[str, set] = defaultdict(set)
    for ed in estado.get("edicoes", []):
        for it in ed.get("itens", []):
            h = _host(it.get("url") or "")
            if h:
                contagem[h] += 1
                quem[h].add(it.get("cliente_id"))
    # a página de imprensa curada substitui a raiz do site do mesmo cliente
    especificas = {_host(pg["url"]) for pg in lista.values() if pg["motivo"] != "site do cliente"}
    lista = {k: pg for k, pg in lista.items()
             if not (pg["motivo"] == "site do cliente" and _host(pg["url"]) in especificas)}
    ja = {_host(pg["url"]) for pg in lista.values()}
    for h, n in sorted(contagem.items(), key=lambda x: -x[1]):
        # host já na lista por um caminho próprio (sicoob.com.br/web/<cooperativa>)
        # não ganha uma segunda entrada genérica pela raiz
        if n < MIN_LEITURA or h in cobertos or h in ja or h in GRANDE_IMPRENSA:
            continue
        for cid in sorted(c for c in quem[h] if c):
            poe("https://" + h + "/", cid, f"rendeu {n} notícias no histórico")
    return list(lista.values())


def _dominio(contagem: dict[str, int]) -> str:
    """O host mais frequente daquele veiculo; '?' se nenhuma URL foi parseavel."""
    if not contagem:
        return "?"
    return max(contagem.items(), key=lambda x: x[1])[0]


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    estado = carrega(Path(sys.argv[1]))
    d = dossie(estado)
    extras = complementares(estado)
    ler = leitura(estado)

    if not d["linhas"]:
        print("DOSSIÊ DE FONTES: sem histórico ainda. Use apenas as camadas (a) e (b).")
        _imprime_complementares(extras)
        _imprime_leitura(ler)
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
    _imprime_complementares(extras)
    _imprime_leitura(ler)


def _imprime_leitura(ler: list[dict]) -> None:
    if not ler:
        return
    print()
    print(f"=== LEITURA DIRETA — camada (d): {len(ler)} páginas, NENHUMA gasta busca ===")
    print("Leia TODAS, com WebFetch, pedindo as manchetes dos últimos 3 dias com data e link.")
    print("Já estão fora as que a camada (e) lê por feed. Abra a matéria antes de usar.")
    print("Página que recusar acesso é pulada e anotada — nunca contornada.")
    for i, pg in enumerate(ler, 1):
        quem = ", ".join(pg["clientes"]) or "carteira toda"
        print(f"  {i:2d}. {pg['url']}  — {quem} ({pg['motivo']})")


def _imprime_complementares(extras: list[str]) -> None:
    if not extras:
        return
    print()
    print("--- fontes complementares, curadas à mão (fontes/complementares.json) ---")
    print("Para os clientes que o histórico não alcança. Leia as páginas na camada (d),")
    print("faça as buscas na camada (a) e use os nomes das pessoas na segunda passada.")
    print("Página que não abrir ou recusar acesso é pulada — nunca contornada.")
    for l in extras:
        print(f"  {l}")


if __name__ == "__main__":
    main()
