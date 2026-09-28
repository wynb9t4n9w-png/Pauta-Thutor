#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes da camada (e), sem rede: feeds sintéticos e casos que já apareceram.

    python3 tools/teste_feeds.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feeds  # noqa: E402

TZ = feeds.TZ
FIM = datetime(2026, 9, 24, 2, 20, tzinfo=TZ)
INICIO = FIM - timedelta(hours=72)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Teste</title>
<item><title>Matéria fixada há meses</title><link>https://x.com/fixada/</link>
  <pubDate>Mon, 01 Jan 2024 10:00:00 +0000</pubDate><description>velha</description></item>
<item><title>CCEE lança nova ferramenta no SCDE</title><link>https://x.com/a/</link>
  <pubDate>Tue, 23 Sep 2026 14:00:00 +0000</pubDate>
  <description><![CDATA[<p>A C&acirc;mara de Comercializa&ccedil;&atilde;o anuncia...</p>]]></description></item>
<item><title>Leilão de baterias</title><link>https://x.com/b/</link>
  <pubDate>2026-09-22 15:40:00</pubDate><description>Sem cliente no resumo.</description>
  <content:encoded><![CDATA[<p>Segundo a Cemig, a demanda cresce.</p>]]></content:encoded></item>
<item><title>Tigre é visto no zoológico</title><link>https://x.com/c/</link>
  <pubDate>Tue, 23 Sep 2026 10:00:00 +0000</pubDate><description>Grupo Tigre? Não: o animal.</description></item>
<item><title>SEBRAE PARA abre inscrições</title><link>https://x.com/d/</link>
  <pubDate>Tue, 23 Sep 2026 09:00:00 -0300</pubDate><description>curso gratuito</description></item>
<item><title>Notícia de uma semana atrás sobre a Cemig</title><link>https://x.com/e/</link>
  <pubDate>Tue, 16 Sep 2026 09:00:00 +0000</pubDate><description>fora da janela</description></item>
<item><title>Notícia da Cemig já publicada ontem</title><link>https://x.com/f</link>
  <pubDate>Tue, 23 Sep 2026 08:00:00 +0000</pubDate><description>repetida</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title>
<entry><title>Taesa anuncia dividendos</title>
  <link rel="alternate" href="https://y.com/taesa"/><published>2026-09-23T12:00:00Z</published>
  <summary>R$ 0,60 por unit</summary></entry>
</feed>"""

CLIENTES = [
    {"id": "ccee", "nome": "CCEE", "ativo": True},
    {"id": "cemig", "nome": "CEMIG", "ativo": True},
    {"id": "tigre", "nome": "TIGRE", "ativo": True, "excluir": ["zoológico", "onça"]},
    {"id": "sebrae-pa", "nome": "SEBRAE/PA", "ativo": True},
    {"id": "taesa", "nome": "TAESA", "ativo": True},
    {"id": "inativo", "nome": "INATIVO", "ativo": False},
]
TERMOS = {
    "ccee": ["CCEE", "Câmara de Comercialização de Energia Elétrica"],
    "cemig": ["Cemig"],
    "tigre": ["Grupo Tigre", "Tigre S.A."],
    "sebrae-pa": ["Sebrae Pará"],
    "taesa": ["Taesa"],
}

falhas = []


def confere(nome, cond, detalhe=""):
    print(("ok    " if cond else "FALHOU ") + nome + ("" if cond else "  — " + detalhe))
    if not cond:
        falhas.append(nome)


def roda():
    itens = feeds.ler_feed(RSS)
    confere("lê os 7 itens do RSS", len(itens) == 7, str(len(itens)))
    confere("limpa HTML e entidades do resumo",
            itens[1]["resumo"].startswith("A Câmara de Comercialização"), itens[1]["resumo"])
    confere("data sem fuso vira horário de São Paulo",
            itens[2]["publicado"] == datetime(2026, 9, 22, 15, 40, tzinfo=TZ), str(itens[2]["publicado"]))
    confere("lê content:encoded", "Segundo a Cemig" in itens[2]["corpo"], itens[2]["corpo"])

    atom = feeds.ler_feed(ATOM)
    confere("lê Atom", len(atom) == 1 and atom[0]["url"] == "https://y.com/taesa", str(atom))

    try:
        feeds.ler_feed("<html><body>Just a moment...</body></html>")
        confere("página de bloqueio não passa por feed", False, "não levantou erro")
    except ValueError:
        confere("página de bloqueio não passa por feed", True)

    confere("casa sem acento e sem caixa", feeds.casa(["Sebrae Pará"], "SEBRAE PARA abre") == "Sebrae Pará")
    confere("não casa pedaço de palavra", feeds.casa(["Taesa"], "a Taesabras informou") is None)
    confere("casa sigla com barra", feeds.casa(["Sebrae/MT"], "o Sebrae/MT lançou") == "Sebrae/MT")

    lidos = [({"nome": "Setorial"}, itens), ({"nome": "Atom"}, atom)]
    publicadas = {"https://x.com/f"}
    c = feeds.candidatos(lidos, CLIENTES, TERMOS, INICIO, FIM, publicadas)
    por = {(x["cliente_id"], x["url"].rstrip("/")): x for x in c}

    confere("CCEE no título vira candidato",
            ("ccee", "https://x.com/a") in por and por[("ccee", "https://x.com/a")]["onde"] == "titulo")
    confere("Cemig só no corpo vem marcada como 'corpo'",
            por.get(("cemig", "https://x.com/b"), {}).get("onde") == "corpo")
    confere("'excluir' do cliente derruba falso positivo (zoológico)",
            ("tigre", "https://x.com/c") not in por)
    confere("Sebrae Pará casa em maiúsculas sem acento", ("sebrae-pa", "https://x.com/d") in por)
    confere("Atom entra no cruzamento", ("taesa", "https://y.com/taesa") in por)
    confere("fora da janela não entra", not any(u.endswith("/e") for _, u in por))
    confere("matéria fixada antiga não entra", not any(u.endswith("/fixada") for _, u in por))
    confere("url já publicada não volta", ("cemig", "https://x.com/f") not in por)

    proprio = [({"nome": "ASN Pará", "cliente": "sebrae-pa"},
                [{"titulo": "Qualquer pauta da agência", "url": "https://pa.x/1", "resumo": "",
                  "corpo": "", "publicado": FIM - timedelta(hours=5)}]),
               ({"nome": "Feed do inativo", "cliente": "inativo"},
                [{"titulo": "x", "url": "https://i.x/1", "resumo": "", "corpo": "",
                  "publicado": FIM - timedelta(hours=5)}])]
    c2 = feeds.candidatos(proprio, CLIENTES, TERMOS, INICIO, FIM, set())
    confere("feed próprio: todo item é do cliente, sem precisar de termo",
            len(c2) == 1 and c2[0]["cliente_id"] == "sebrae-pa" and c2[0]["onde"] == "feed_proprio", str(c2))
    confere("cliente inativo não recebe candidato", all(x["cliente_id"] != "inativo" for x in c2))

    confere("sem termo no registro, usa nome e razão",
            feeds.termos_do({"id": "novo", "nome": "Nova Empresa", "razao": "Nova Empresa S.A."}, {})
            == ["Nova Empresa", "Nova Empresa S.A."])

    # saúde: fonte que vinha bem e caiu hoje precisa virar alerta
    hist = {
        "2026-09-20": {"MegaWhat": {"status": "ok", "na_janela": 9, "alcancou_janela": True}},
        "2026-09-21": {"MegaWhat": {"status": "ok", "na_janela": 7, "alcancou_janela": True}},
        "2026-09-22": {"MegaWhat": {"status": "ok", "na_janela": 8, "alcancou_janela": True}},
        "2026-09-23": {"MegaWhat": {"status": "http_403", "na_janela": 0}},
    }
    av = feeds.alertas(hist, "2026-09-23")
    confere("alerta quando fonte que vinha ok passa a falhar", any("passou a falhar" in a for a in av), str(av))

    hist2 = {d: {"X": {"status": "ok", "na_janela": 5, "alcancou_janela": True}} for d in
             ("2026-09-18", "2026-09-19", "2026-09-20")}
    hist2.update({d: {"X": {"status": "ok", "na_janela": 0, "alcancou_janela": True}} for d in
                  ("2026-09-21", "2026-09-22", "2026-09-23")})
    av2 = feeds.alertas(hist2, "2026-09-23")
    confere("alerta quando fonte seca por 3 noites", any("sem nenhum item" in a for a in av2), str(av2))

    hist3 = {"2026-09-23": {"Y": {"status": "ok", "na_janela": 4, "alcancou_janela": False,
                                  "alcance_horas": 30}}}
    confere("alerta quando o feed não alcança a janela",
            any("não alcançou" in a for a in feeds.alertas(hist3, "2026-09-23")))

    hist4 = {"2026-09-23": {"Z": {"status": "ok", "na_janela": 4, "alcancou_janela": False,
                                  "alcance_horas": 58, "parcial_aceito": True}}}
    confere("feed que não pagina (parcial conhecido) não gera alerta diário",
            feeds.alertas(hist4, "2026-09-23") == [])

    print()
    if falhas:
        print("%d teste(s) falharam." % len(falhas))
        return 1
    print("todos os testes passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(roda())
