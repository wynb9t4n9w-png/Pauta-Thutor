#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Boletim de qualidade da Pauta Thutor, a partir do histórico de edições.

    python3 tools/qualidade.py <estado.html|estado.json> [--dias N] [--links]

    --dias N   quantas edições recentes avaliar (padrão 14), comparadas com as N
               anteriores quando o histórico permitir
    --links    também abre cada matéria do período: confere se o link responde e
               se o texto cita o cliente (lento: uma requisição por item)

Existe por causa do estudo de 30/09/2026, feito à mão, que achou em uma tarde o
que nenhum indicador diário mostrava: as buscas tinham caído de ~400 para ~130
com a chegada dos feeds, a editoria gente para 1 item por dia, o Sistema S
passava de 60% do jornal e a mesma pauta saía em edições seguidas. Cada número
estava lá; faltava alguém somar. Este script soma.

Não julga sozinho: mostra o número, compara com o período anterior e aponta o
que merece conversa. Qualidade de clipping é decisão editorial.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from texto import LIMIAR_REPETICAO, semelhanca, url_canonica  # noqa: E402
import feeds  # noqa: E402

SISTEMA_S = ("sebrae", "sesc", "sescoop", "senai", "senac", "sesi")
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def carrega(caminho):
    txt = Path(caminho).read_text(encoding="utf8")
    if str(caminho).endswith(".json"):
        return json.loads(txt)
    m = re.search(r"/\*DADOS\*/(.*?)/\*FIM\*/", txt, re.S)
    if not m:
        raise SystemExit("FALHA: bloco /*DADOS*/ não encontrado em %s" % caminho)
    return json.loads(m.group(1))


def do_sistema_s(cid):
    return (cid or "").split("-")[0] in SISTEMA_S


def media(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def repeticoes(edicoes, dias=10):
    """Pares (mesmo cliente, edições diferentes, até `dias` de distância) cuja
    manchete conta a mesma pauta."""
    itens = [(e["data"], i) for e in edicoes for i in e.get("itens") or []]
    pares = []
    for a in range(len(itens)):
        da, ia = itens[a]
        for b in range(a + 1, len(itens)):
            db, ib = itens[b]
            if da == db or ia.get("cliente_id") != ib.get("cliente_id"):
                continue
            if abs((date.fromisoformat(da) - date.fromisoformat(db)).days) > dias:
                continue
            nota = semelhanca(ia.get("titulo"), ib.get("titulo"))
            if nota >= LIMIAR_REPETICAO:
                pares.append((nota, da, db, ia.get("titulo", ""), ib.get("titulo", "")))
    return sorted(pares, reverse=True)


def indicadores(edicoes, clientes):
    ativos = [c for c in clientes if c.get("ativo") is not False]
    itens = [i for e in edicoes for i in e.get("itens") or []]
    n = max(1, len(edicoes))
    ed = Counter(i.get("editoria") for i in itens)
    pautas = Counter(feeds.classifica_pauta(i.get("titulo", ""), i.get("resumo", "")) for i in itens)
    uteis = [len(e.get("itens") or []) for e in edicoes if date.fromisoformat(e["data"]).weekday() not in (0,)]
    segundas = [len(e.get("itens") or []) for e in edicoes if date.fromisoformat(e["data"]).weekday() == 0]
    cob = [e.get("cobertura") or {} for e in edicoes]
    camadas = Counter()
    for c in cob:
        camadas.update(c.get("itens_por_camada") or {})
    presentes = {i.get("cliente_id") for i in itens}
    por_cliente = Counter(i.get("cliente_id") for i in itens)
    maior = por_cliente.most_common(1)[0] if por_cliente else (None, 0)
    return {
        "edicoes": len(edicoes),
        "itens_por_edicao": len(itens) / n,
        "itens_seg": media(segundas) if segundas else None,
        "itens_demais": media(uteis),
        "clientes_por_edicao": media(len({i.get("cliente_id") for i in e.get("itens") or []}) for e in edicoes),
        "ativos": len(ativos),
        "nunca": [c["nome"] for c in ativos if c["id"] not in presentes],
        "pct_sistema_s": 100 * sum(1 for i in itens if do_sistema_s(i.get("cliente_id"))) / max(1, len(itens)),
        "maior_cliente": (maior[0], 100 * maior[1] / max(1, len(itens))),
        "gente_por_edicao": ed["gente"] / n,
        "risco_por_edicao": ed["risco"] / n,
        "pct_servico": 100 * pautas["servico"] / max(1, len(itens)),
        "buscas": media(c.get("buscas", 0) for c in cob if c.get("buscas")),
        "camadas": {k: v / n for k, v in sorted(camadas.items())},
        "veiculos_por_edicao": media(len({i.get("fonte") for i in e.get("itens") or []}) for e in edicoes),
    }


def seta(atual, antes, melhor_se_maior=True, tol=0.1):
    if antes is None or atual is None:
        return ""
    if antes == 0:
        return "" if atual == 0 else ("  ↑" if melhor_se_maior else "  ↑ (!)")
    var = (atual - antes) / abs(antes)
    if abs(var) < tol:
        return "  ="
    subiu = var > 0
    ruim = subiu != melhor_se_maior
    return ("  ↑" if subiu else "  ↓") + (" (!)" if ruim else "")


def confere_links(itens_com_data, clientes, termos_cfg):
    """Abre cada matéria: o link responde? o texto cita o cliente?"""
    cli = {c["id"]: c for c in clientes}
    agente = "PautaThutor/1.0 (verificacao de qualidade; +https://wynb9t4n9w-png.github.io/Pauta-Thutor/)"

    def abre(url):
        r = subprocess.run(["curl", "-s", "-L", "--max-time", "20", "-A", agente,
                            "-w", "\n%{http_code}", url], capture_output=True)
        corpo, _, cod = r.stdout.rpartition(b"\n")
        return cod.decode() or "000", feeds.sem_html(corpo.decode("utf-8", "replace"))

    with ThreadPoolExecutor(8) as ex:
        paginas = list(ex.map(lambda x: abre(x[1]["url"]), itens_com_data))
    status = Counter(cod for cod, _ in paginas)
    cita = nao_cita = 0
    suspeitos = []
    for (data, it), (cod, texto_) in zip(itens_com_data, paginas):
        if cod != "200" or len(texto_) < 800 or it.get("editoria") == "setor":
            continue
        c = cli.get(it.get("cliente_id"), {})
        termos = feeds.termos_do(c, termos_cfg) + [c.get("nome", "")]
        if do_sistema_s(c.get("id")):
            termos.append("Sebrae" if c["id"].startswith("sebrae") else "Sesc")
        if feeds.casa([t for t in termos if t], texto_):
            cita += 1
        else:
            nao_cita += 1
            suspeitos.append("%s %s: %s" % (data[5:], c.get("nome", "?"), it.get("titulo", "")[:70]))
    return status, cita, nao_cita, suspeitos


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("estado")
    ap.add_argument("--dias", type=int, default=14)
    ap.add_argument("--links", action="store_true")
    a = ap.parse_args()

    estado = carrega(a.estado)
    clientes = estado.get("clientes") or []
    eds = sorted(estado.get("edicoes") or [], key=lambda e: e["data"])
    atual, antes = eds[-a.dias:], eds[-2 * a.dias:-a.dias]
    if not atual:
        raise SystemExit("nenhuma edição no estado")

    x = indicadores(atual, clientes)
    y = indicadores(antes, clientes) if len(antes) >= 3 else None
    nomes = {c["id"]: c["nome"] for c in clientes}

    def linha(rotulo, chave, fmt="%.1f", maior_melhor=True):
        v = x[chave]
        txt = fmt % v if v is not None else "—"
        ref = ("   (antes " + (fmt % y[chave]) + ")") if y and y.get(chave) is not None else ""
        print("  %-34s %8s%s%s" % (rotulo, txt, ref, seta(v, y[chave] if y else None, maior_melhor)))

    print("BOLETIM DE QUALIDADE · %d edições, %s a %s%s"
          % (x["edicoes"], atual[0]["data"], atual[-1]["data"],
             ("  · comparado com as %d anteriores" % y["edicoes"]) if y else ""))
    print()
    print("Volume e alcance")
    linha("notícias por edição", "itens_por_edicao")
    if x["itens_seg"] is not None:
        print("  %-34s %8.1f   (segunda) · %.1f (demais dias)" % ("  — por dia da semana", x["itens_seg"], x["itens_demais"]))
    linha("clientes na pauta, por edição", "clientes_por_edicao")
    linha("veículos distintos, por edição", "veiculos_por_edicao")
    print("  %-34s %8s" % ("clientes sem nenhum item", "%d de %d" % (len(x["nunca"]), x["ativos"])))
    if x["nunca"]:
        print("      " + ", ".join(x["nunca"]))
    print()
    print("Relevância para a Thutor")
    linha("gente & cultura, por edição", "gente_por_edicao")
    linha("alertas de risco, por edição", "risco_por_edicao")
    linha("conteúdo de serviço (%)", "pct_servico", "%.0f%%", maior_melhor=False)
    linha("Sistema S no jornal (%)", "pct_sistema_s", "%.0f%%", maior_melhor=False)
    mc, pct = x["maior_cliente"]
    print("  %-34s %8s" % ("maior cliente", "%s, %.0f%%" % (nomes.get(mc, mc), pct)))
    print()
    print("Esforço da coleta")
    linha("buscas por noite", "buscas", "%.0f")
    print("  %-34s %s" % ("itens por camada, por noite",
                          " · ".join("%s %.1f" % (k, v) for k, v in x["camadas"].items()) or "—"))
    print()
    pares = repeticoes(atual)
    print("Repetição")
    print("  %-34s %8d" % ("pares de pauta repetida", len(pares)))
    for nota, da, db, ta, tb in pares[:5]:
        print("      %.2f  %s '%s'  ≈  %s '%s'" % (nota, da[5:], ta[:48], db[5:], tb[:48]))

    if a.links:
        reg = json.loads((Path(__file__).resolve().parent.parent / "fontes" / "feeds.json").read_text(encoding="utf8"))
        termos_cfg = {k: v for k, v in (reg.get("termos") or {}).items() if not k.startswith("_")}
        itens = [(e["data"], i) for e in atual for i in e.get("itens") or []]
        status, cita, nao_cita, suspeitos = confere_links(itens, clientes, termos_cfg)
        print()
        print("Integridade (abrindo cada matéria)")
        print("  %-34s %s" % ("respostas dos links", dict(status)))
        print("      403 costuma ser site que recusa servidor e abre no navegador; 000 é tempo esgotado.")
        total = cita + nao_cita
        if total:
            print("  %-34s %8s" % ("citam o cliente no texto", "%d de %d (%.0f%%)" % (cita, total, 100 * cita / total)))
        for s in suspeitos[:8]:
            print("      não cita: " + s)

    print()
    print("Pontos de atenção")
    avisos = []
    if y and x["buscas"] < 0.6 * y["buscas"]:
        avisos.append("as buscas caíram %.0f%% contra o período anterior" % (100 * (1 - x["buscas"] / y["buscas"])))
    if x["gente_por_edicao"] < 2:
        avisos.append("menos de 2 itens de gente & cultura por edição — é a editoria mais útil para a Thutor")
    if x["pct_sistema_s"] > 55:
        avisos.append("o Sistema S ocupa %.0f%% do jornal" % x["pct_sistema_s"])
    if x["pct_servico"] > 15:
        avisos.append("%.0f%% dos itens têm cara de conteúdo de serviço (dica, curso, 'saiba como')" % x["pct_servico"])
    if len(pares) > x["edicoes"]:
        avisos.append("mais de um par de pauta repetida por edição")
    for av in avisos or ["nenhum."]:
        print("  - " + av)
    return 0


if __name__ == "__main__":
    sys.exit(main())
