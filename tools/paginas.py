#!/usr/bin/env python3
"""
Vigia de páginas: a leitura direta (camada d) feita por script, para as fontes
que NÃO têm feed.

Uso:
    python3 tools/paginas.py <estado.html|estado.json> --saida paginas.json \\
        --vistas fontes/paginas_vistas.json

Por que existe. De 01 a 05/10/2026 a coleta bateu toda noite no teto de 200
buscas por sessão, e as 200 buscas renderam de 0 a 2 notícias. A leitura direta,
que em setembro rendia de 12 a 29 por noite sem gastar busca, caiu para 0 a 4:
dependia de a coleta lembrar de abrir cada página, e deixou de lembrar. CCEE e
Sesc DF sumiram do jornal.

Como funciona. Lê cada página da lista LEITURA DIRETA do dossiê (tools/fontes.py),
uma requisição por vez, com o mesmo agente honesto e o mesmo respeito ao
robots.txt da camada (e). Guarda em fontes/paginas_vistas.json uma impressão
(hash) de cada link de manchete que já viu. Na noite seguinte, o que for NOVO é
pista:
  - numa sala de imprensa curada, todo link novo é do cliente;
  - na raiz do site de um cliente, só o link novo com cara de notícia (caminho com
    /noticia, /imprensa, /blog, ano...) ou com o nome do cliente no texto — loja
    on-line cria produto novo todo dia;
  - num veículo de terceiros, só o link novo cujo texto nomeia um cliente, com os
    mesmos termos, contexto e exclusões da camada (e).
Página vista pela primeira vez vira linha de base e não gera pista: sem data no
link, não há como saber se é de hoje ou de 2019.

Pista não é notícia. Página de listagem não traz data confiável: a coleta abre
cada uma e só usa o que confirmar como publicado na janela.
"""

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fontes  # noqa: E402
from feeds import (REGISTRO_PADRAO, TZ, Leitor, carrega_estado, casa,  # noqa: E402
                   casa_contexto, classifica_pauta, termos_do)
from texto import LIMIAR_REPETICAO, mesmo_titulo, semelhanca, url_canonica  # noqa: E402

VISTAS_PADRAO = fontes.FEEDS.parent / "paginas_vistas.json"
TITULO_MIN = 25          # texto de link mais curto que isto é menu, botão ou "saiba mais"
TITULO_MAX = 220
GUARDA_POR_PAGINA = 400  # impressões guardadas por página
DIAS_REPETICAO = 10
CARA_DE_NOTICIA = re.compile(
    r"/(noticias?|news|imprensa|press|blog|releases?|midia|na-midia|comunicados?|artigos?|"
    r"publicacoes|novidades|20\d\d)(/|-|$)", re.I)
NAO_E_MANCHETE = re.compile(
    r"(cookies|privacidade|termos de uso|fale conosco|trabalhe conosco|ouvidoria|"
    r"política de|todos os direitos|assine|newsletter|login|cadastre-se)", re.I)
ESQUEMAS_FORA = ("mailto:", "tel:", "javascript:", "whatsapp:")
ARQUIVOS_FORA = re.compile(r"\.(jpe?g|png|gif|webp|svg|css|js|zip|mp4|mp3)(\?|$)", re.I)


def impressao(url: str) -> str:
    return hashlib.sha1(url_canonica(url).encode("utf8")).hexdigest()[:12]


def manchetes(pagina_url: str, corpo: bytes) -> list[dict]:
    """Links com texto de manchete: [{url, titulo}], sem repetir url."""
    t = corpo.decode("utf8", "replace")
    t = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", t, flags=re.S | re.I)
    vistos, saida = {}, []
    for href, miolo in re.findall(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", t, re.S | re.I):
        href = html.unescape(href.strip())
        if not href or href.lower().startswith(ESQUEMAS_FORA) or ARQUIVOS_FORA.search(href):
            continue
        url = urljoin(pagina_url, href)
        if not url.startswith(("http://", "https://")):
            continue
        texto = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", miolo))).strip()
        # Liferay e afins deixam o endereço da miniatura no texto do link
        # ("?version=1.0&t=17900...&imageThumbnail=3 Esporte e Lazer Sesc-DF..."), visto em 06/10/2026.
        texto = " ".join(w for w in texto.split()
                         if not (w.startswith(("?", "http", "/")) or ("=" in w and "&" in w))).strip()
        if not (TITULO_MIN <= len(texto) <= TITULO_MAX) or NAO_E_MANCHETE.search(texto):
            continue
        chave = url_canonica(url)
        if chave in vistos:
            if len(texto) > len(saida[vistos[chave]]["titulo"]):
                saida[vistos[chave]]["titulo"] = texto
            continue
        vistos[chave] = len(saida)
        saida.append({"url": url, "titulo": texto})
    return saida


def pistas(pagina: dict, novos: list[dict], ativos: dict, termos: dict, contexto: dict,
           publicadas: set, recentes: dict) -> list[dict]:
    """Cruza os links novos de uma página com a carteira."""
    propria = pagina["motivo"] in ("site do cliente", "sala de imprensa") and len(pagina["ids"]) == 1
    dono = pagina["ids"][0] if propria else None
    curada = pagina["motivo"] == "sala de imprensa"
    fonte = urlparse(pagina["url"]).netloc.lower().removeprefix("www.")
    saida = []
    for ln in novos:
        if url_canonica(ln["url"]) in publicadas:
            continue
        achados = []
        if dono and dono in ativos:
            nome_cli = casa(termos[dono], ln["titulo"])
            if curada or nome_cli or CARA_DE_NOTICIA.search(urlparse(ln["url"]).path):
                achados.append((dono, "pagina_propria", nome_cli))
        else:
            for cid, c in ativos.items():
                if c.get("excluir") and casa(c["excluir"], ln["titulo"]):
                    continue
                t = casa(termos[cid], ln["titulo"]) or casa_contexto(contexto.get(cid), ln["titulo"])
                if t:
                    achados.append((cid, "titulo", t))
        for cid, onde, termo in achados:
            parecido = None
            for data_ant, tit_ant in recentes.get(cid, []):
                if mesmo_titulo(ln["titulo"], tit_ant):
                    parecido = "identico"
                    break
                if semelhanca(ln["titulo"], tit_ant) >= LIMIAR_REPETICAO:
                    parecido = {"data": data_ant, "titulo": tit_ant}
                    break
            if parecido == "identico":
                continue
            saida.append({
                "cliente_id": cid,
                "cliente": ativos[cid].get("nome", cid),
                "titulo": ln["titulo"],
                "url": ln["url"],
                "data": None,
                "fonte": fonte,
                "pagina": pagina["url"],
                "tipo": "pagina",
                "onde": onde,
                "termo": termo,
                "nome_no_titulo": bool(casa(termos[cid], ln["titulo"])),
                "pauta": classifica_pauta(ln["titulo"]),
                **({"parecido_com": parecido} if parecido else {}),
            })
    return saida


def vigia(estado: dict, vistas: dict, leitor, hoje: str, registro: dict) -> tuple[list, list, dict]:
    """Lê as páginas, devolve (pistas, relatório por página, vistas atualizadas)."""
    termos_cfg = {k: v for k, v in (registro.get("termos") or {}).items() if not k.startswith("_")}
    contexto = {k: v for k, v in (registro.get("contexto") or {}).items() if not k.startswith("_")}
    ativos = {c["id"]: c for c in estado.get("clientes", []) if c.get("ativo") is not False}
    termos = {cid: termos_do(c, termos_cfg) for cid, c in ativos.items()}
    publicadas = {url_canonica(i.get("url")) for e in estado.get("edicoes") or []
                  if e.get("data", "") < hoje for i in e.get("itens") or []}
    recentes: dict[str, list] = {}
    for e in (estado.get("edicoes") or [])[:DIAS_REPETICAO]:
        if e.get("data", "") < hoje:
            for i in e.get("itens") or []:
                recentes.setdefault(i.get("cliente_id"), []).append((e["data"], i.get("titulo") or ""))

    todas, relatorio, novas_vistas = [], [], {}
    for pg in fontes.leitura(estado):
        url = pg["url"]
        # A chave é a impressão do endereço, não o endereço: o repositório é
        # público, e a lista inclui o site de cada cliente.
        chave = impressao(url)
        antes = vistas.get(chave) or {}
        reg = {"url": url, "clientes": pg["clientes"], "status": "ok", "links": 0, "novos": 0, "pistas": 0,
               "antes": antes.get("status")}
        if not leitor.permite(url):
            # Leitor.permite trata robots.txt que não respondeu (rede, certificado,
            # 5xx) como proibição total, pela RFC 9309. Para o relatório, os dois
            # casos são diferentes: proibição se respeita; falha de rede a coleta
            # pode tentar pela ferramenta dela.
            base = "%s://%s" % (urlparse(url).scheme, urlparse(url).netloc)
            reg["status"] = "robots_sem_resposta" if getattr(leitor, "robots", {}).get(base) is False \
                else "proibido_robots"
        else:
            st, corpo = leitor.baixar(url)
            if st != 200:
                reg["status"] = "rede" if st == 0 else "http_%d" % st
            else:
                links = manchetes(url, corpo)
                reg["links"] = len(links)
                if not links:
                    reg["status"] = "sem_manchetes"
                conhecidas = set(antes.get("links") or [])
                novos = [ln for ln in links if impressao(ln["url"]) not in conhecidas]
                if not antes.get("links"):
                    reg["status"] = "linha_de_base" if links else reg["status"]
                    novos = []
                reg["novos"] = len(novos)
                achadas = pistas(pg, novos, ativos, termos, contexto, publicadas, recentes)
                reg["pistas"] = len(achadas)
                todas.extend(achadas)
                guardar = [impressao(ln["url"]) for ln in links]
                guardar += [h for h in antes.get("links") or [] if h not in set(guardar)]
                novas_vistas[chave] = {"links": guardar[:GUARDA_POR_PAGINA], "visto_em": hoje,
                                       "status": reg["status"]}
        if chave not in novas_vistas:
            # falhou hoje: guarda o que sabia, para não perder a linha de base
            novas_vistas[chave] = {**antes, "status": reg["status"]} if antes else {"links": [], "status": reg["status"]}
        relatorio.append(reg)

    ordem = {"pagina_propria": 0, "titulo": 1}
    ordem_pauta = {"risco": 0, "gente": 1, "estrategia": 2, "geral": 3, "servico": 4}
    todas.sort(key=lambda c: (bool(c.get("parecido_com")), ordem[c["onde"]], ordem_pauta[c["pauta"]],
                              c["cliente"]))
    return todas, relatorio, novas_vistas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("estado")
    ap.add_argument("--saida")
    ap.add_argument("--vistas", default=str(VISTAS_PADRAO))
    ap.add_argument("--registro", default=str(REGISTRO_PADRAO))
    a = ap.parse_args()

    estado = carrega_estado(a.estado)
    registro = json.loads(Path(a.registro).read_text(encoding="utf8"))
    caminho_vistas = Path(a.vistas)
    vistas = {}
    if caminho_vistas.exists():
        try:
            vistas = json.loads(caminho_vistas.read_text(encoding="utf8")).get("paginas", {})
        except ValueError:
            vistas = {}
    hoje = datetime.now(TZ).date().isoformat()
    leitor = Leitor(registro.get("agente") or "PautaThutor/1.0")

    achadas, relatorio, novas = vigia(estado, vistas, leitor, hoje, registro)

    print("camada (d) · vigia de páginas · %d páginas" % len(relatorio))
    print()
    for r in relatorio:
        marca = "ok  " if r["status"] in ("ok", "linha_de_base") else "!!  "
        quem = ", ".join(r["clientes"])[:30] or "carteira"
        print("%s%-16s %3d links · %3d novos · %2d pistas  %s  (%s)"
              % (marca, r["status"], r["links"], r["novos"], r["pistas"], r["url"][:60], quem))
    # O que a coleta abre com WebFetch: o robô não leu, ou leu e não achou manchete
    # (página montada por JavaScript). Proibição do robots.txt fica de fora.
    fora = [r for r in relatorio if r["status"] not in ("ok", "linha_de_base", "proibido_robots")]
    proibidas = [r for r in relatorio if r["status"] == "proibido_robots"]
    caiu = [r for r in relatorio if r.get("antes") in ("ok", "linha_de_base")
            and r["status"] not in ("ok", "linha_de_base")]
    print()
    print("%d pistas para %d clientes. Pista não é notícia: abra cada uma e confirme a data."
          % (len(achadas), len({c["cliente_id"] for c in achadas})))
    for c in achadas:
        print("  %-22s %-14s %s" % (c["cliente"][:22], c["onde"], c["titulo"][:90]))
    if caiu:
        print()
        print("ATENÇÃO — páginas que liam bem e deixaram de ler hoje:")
        for r in caiu:
            print("  - %s: %s (antes: %s)" % (r["url"], r["status"], r["antes"]))
    if fora:
        print()
        print("Páginas que o robô não leu ou em que não achou manchete — a coleta abre estas com WebFetch:")
        for r in fora:
            print("  %s  (%s)" % (r["url"], r["status"]))
    if proibidas:
        print()
        print("Proibidas pelo robots.txt — não ler, nem por outra ferramenta:")
        for r in proibidas:
            print("  %s" % r["url"])

    saida_vistas = {"_sobre": "Impressões dos links de manchete já vistos em cada página da camada (d). "
                              "Gerado por tools/paginas.py; não edite à mão.",
                    "paginas": novas}
    caminho_vistas.parent.mkdir(parents=True, exist_ok=True)
    caminho_vistas.write_text(json.dumps(saida_vistas, ensure_ascii=False, indent=1) + "\n", encoding="utf8")

    if a.saida:
        Path(a.saida).write_text(json.dumps({
            "gerado_em": datetime.now(TZ).isoformat(timespec="minutes"),
            "candidatos": achadas,
            "paginas": relatorio,
            "nao_lidas": [r["url"] for r in fora],
            "proibidas": [r["url"] for r in proibidas],
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
        print()
        print("pistas gravadas em %s" % a.saida)


if __name__ == "__main__":
    main()
