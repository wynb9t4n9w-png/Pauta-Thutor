#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes da camada (e), sem rede: feeds sintéticos e casos que já apareceram.

    python3 tools/teste_feeds.py
"""

import json
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

    # --- estudo de qualidade de 30/09/2026 -----------------------------------
    ctx_tigre = {"nome": ["Tigre"], "com": ["Joinville", "tubos", "Hansen"]}
    confere("nome ambíguo com palavra do ramo casa",
            feeds.casa_contexto(ctx_tigre, "Tigre amplia fábrica em Joinville") == "Tigre (+Joinville)")
    confere("nome ambíguo sem palavra do ramo não casa",
            feeds.casa_contexto(ctx_tigre, "Tigre-de-bengala nasce no zoológico") is None)

    for titulo, esperado in [
        ("Presidente da CCEE assume conselho internacional", "gente"),
        ("Brasília recebe encontro de lideranças do Sesc", "gente"),
        ("Liminar impede CCEE de efetivar desligamento da Electra", "risco"),
        ("Gazin inaugura loja em Acará e supera meta", "estrategia"),
        ("Análise gratuita do Instagram ajuda chef de cozinha a conquistar clientes", "servico"),
        ("Rota Tempo das Águas revela encantos de Santarém", "geral"),
    ]:
        confere("pauta de '%s…' é %s" % (titulo[:32], esperado), feeds.classifica_pauta(titulo) == esperado,
                feeds.classifica_pauta(titulo))

    asn = {"nome": "ASN Pará", "cliente": "sebrae-pa", "marca": "Sebrae"}
    def it(titulo, url, horas=5):
        return {"titulo": titulo, "url": url, "resumo": "", "corpo": "", "publicado": FIM - timedelta(hours=horas)}
    recentes = {"sebrae-pa": [("2026-09-22", "Sebrae promove feira de negócios em Belém"),
                              ("2026-09-22", "Circuito Conexão Financeira chega a Belém e Ananindeua")]}
    c3 = feeds.candidatos([(asn, [
        it("Sebrae promove feira de negócios em Belém", "https://pa.x/republicada"),
        it("Circuito Conexão Financeira chega a Marabá e Parauapebas", "https://pa.x/parecida"),
        it("Sebrae nomeia nova superintendente no Pará", "https://pa.x/nova"),
        it("Dicas para vender mais no Círio", "https://pa.x/dica"),
    ])], CLIENTES, TERMOS, INICIO, FIM, set(), recentes=recentes)
    urls3 = {x["url"].rsplit("/", 1)[-1]: x for x in c3}
    confere("título idêntico a edição recente é descartado", "republicada" not in urls3, str(list(urls3)))
    confere("título parecido fica, mas marcado", "parecido_com" in urls3.get("parecida", {}))
    confere("marca da sala de imprensa conta como nome no título", urls3.get("nova", {}).get("nome_no_titulo") is True)
    confere("pauta de gente reconhecida no candidato", urls3.get("nova", {}).get("pauta") == "gente")
    confere("dica sem o nome do cliente não conta como nome no título",
            urls3.get("dica", {}).get("nome_no_titulo") is False and urls3.get("dica", {}).get("pauta") == "servico")
    confere("parecido vai para o fim da fila", c3[-1]["url"].endswith("parecida"), str([x["url"] for x in c3]))

    hist4 = {"2026-09-23": {"Z": {"status": "ok", "na_janela": 4, "alcancou_janela": False,
                                  "alcance_horas": 58, "parcial_aceito": True}}}
    confere("feed que não pagina (parcial conhecido) não gera alerta diário",
            feeds.alertas(hist4, "2026-09-23") == [])

    # o registro real: nome único (é a chave da saúde) e sem feed de cliente parado
    reg = json.loads((Path(__file__).resolve().parent.parent / "fontes" / "feeds.json").read_text(encoding="utf8"))
    nomes = [f["nome"] for f in reg["feeds"]]
    confere("nomes de feed únicos no registro", len(nomes) == len(set(nomes)),
            str([n for n in nomes if nomes.count(n) > 1]))
    confere("todo feed tem url https", all(f["url"].startswith("https://") for f in reg["feeds"]))
    ctx = reg["contexto"]
    for cid, manchete, casa_ou_nao in [
        ("rocha", "Rocha investe R$ 700 milhões em terminal de Paranaguá", True),
        ("rocha", "Almirante Rocha abre feira com terminais e indústria portuária", False),
        ("atlas", "Dako lança cooktop de indução", True),
        ("atlas", "Atlas geográfico ganha nova edição", False),
        ("tigre", "Tigre vence em Joinville e segue na liderança", False),
        ("crh", "Cidade das Águas: bairro planejado de Joinville sai do papel", True),
        ("neovia", "MPF investiga obra da Neovia na BR-280", True),
    ]:
        confere("contexto real de %s: '%s…'" % (cid, manchete[:30]),
                bool(feeds.casa_contexto(ctx[cid], manchete)) == casa_ou_nao)

    # XML com quebra de linha antes do <?xml (visto no SIMPESC) ainda é feed
    confere("feed com espaço antes do cabeçalho XML é lido",
            len(feeds.ler_feed(b"\n<?xml version='1.0'?><rss><channel><item><title>A</title>"
                               b"<link>https://x/a</link></item></channel></rss>")) == 1)

    # feed parado desde o cadastro: avisa na primeira noite, não todas as noites
    velho = {"status": "ok", "na_janela": 0, "alcancou_janela": True, "mais_novo_horas": 41000}
    confere("feed parado há anos gera alerta",
            any("está parado" in a for a in feeds.alertas({"2026-09-23": {"CRH": velho}}, "2026-09-23")))
    confere("feed parado não repete o alerta toda noite",
            feeds.alertas({"2026-09-22": {"CRH": velho}, "2026-09-23": {"CRH": velho}}, "2026-09-23") == [])
    vivo = dict(velho, mais_novo_horas=30)
    confere("feed ativo não é parado",
            feeds.alertas({"2026-09-23": {"CRH": vivo}}, "2026-09-23") == [])

    print()
    if falhas:
        print("%d teste(s) falharam." % len(falhas))
        return 1
    print("todos os testes passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(roda())
