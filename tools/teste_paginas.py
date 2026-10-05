#!/usr/bin/env python3
"""Testes do vigia de páginas (tools/paginas.py), sem rede.

    python3 tools/teste_paginas.py
"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paginas  # noqa: E402

falhas = 0


def confere(nome, cond, detalhe=""):
    global falhas
    print(("ok    " if cond else "FALHA ") + nome + ("" if cond else "  " + detalhe))
    falhas += 0 if cond else 1


def html_de(*links):
    return ("<html><body><nav><a href='/contato'>Fale conosco agora mesmo pelo formulário</a></nav>"
            + "".join("<a href='%s'><h3>%s</h3></a>" % (u, t) for u, t in links)
            + "<a href='mailto:x@y.z'>Escreva para a nossa assessoria de imprensa</a>"
            + "<a href='/foto.jpg'>Foto da nova fábrica inaugurada ontem em Joinville</a>"
            + "<a href='/curto'>Saiba mais</a></body></html>").encode("utf8")


class LeitorFalso:
    def __init__(self, paginas_html, bloqueadas=()):
        self.paginas_html, self.bloqueadas = paginas_html, set(bloqueadas)

    def permite(self, url):
        return url not in self.bloqueadas

    def baixar(self, url):
        if url in self.paginas_html:
            return 200, self.paginas_html[url]
        return 403, b""


ESTADO = {
    "clientes": [
        {"id": "sesc", "nome": "SESC/DF", "site": "sescdf.com.br", "excluir": []},
        {"id": "gazin", "nome": "GAZIN", "site": "gazin.com.br", "excluir": []},
        {"id": "tigre", "nome": "TIGRE", "site": "", "excluir": ["Criciúma"]},
        {"id": "ccee", "nome": "CCEE", "site": "ccee.org.br", "excluir": []},
    ],
    "edicoes": [{"data": "2026-10-04", "itens": [
        {"cliente_id": "sesc", "titulo": "Sesc DF abre inscrições para a corrida do comerciário",
         "url": "https://www.sescdf.com.br/noticias/ja-publicada"}]}],
}
REGISTRO = {"termos": {"tigre": ["Grupo Tigre"], "sesc": ["Sesc DF"], "gazin": ["Gazin"], "ccee": ["CCEE"]},
            "contexto": {"tigre": {"nome": ["Tigre"], "com": ["tubos", "saneamento"]}}}
LISTA = [
    {"url": "https://sescdf.com.br", "clientes": ["SESC/DF"], "ids": ["sesc"], "motivo": "site do cliente"},
    {"url": "https://gazin.com.br", "clientes": ["GAZIN"], "ids": ["gazin"], "motivo": "site do cliente"},
    {"url": "https://www.tigre.com.br/tigre-na-midia", "clientes": ["TIGRE"], "ids": ["tigre"],
     "motivo": "sala de imprensa"},
    {"url": "https://economia.exemplo/", "clientes": ["TIGRE"], "ids": ["tigre"],
     "motivo": "rendeu 4 notícias no histórico"},
    {"url": "https://ccee.org.br", "clientes": ["CCEE"], "ids": ["ccee"], "motivo": "site do cliente"},
]


def roda():
    noite1 = {
        "https://sescdf.com.br": html_de(("/noticias/velha", "Sesc DF promove festival de teatro no Gama")),
        "https://gazin.com.br": html_de(("/produto/geladeira-1", "Geladeira Frost Free 380 litros inox")),
        "https://www.tigre.com.br/tigre-na-midia": html_de(("https://x.com/a", "Tigre lança linha antiga de tubos")),
        "https://economia.exemplo/": html_de(("/a", "Indústria catarinense cresce no trimestre")),
    }
    noite2 = {
        "https://sescdf.com.br": html_de(
            ("/noticias/velha", "Sesc DF promove festival de teatro no Gama"),
            ("/noticias/nova", "Sesc DF anuncia nova diretora regional"),
            ("/noticias/ja-publicada", "Sesc DF abre inscrições para a corrida do comerciário"),
            ("/agenda/oficina-de-pintura", "Oficina de pintura em aquarela para iniciantes")),
        "https://gazin.com.br": html_de(
            ("/produto/geladeira-1", "Geladeira Frost Free 380 litros inox"),
            ("/produto/fogao-2", "Fogão 5 bocas com acendimento automático"),
            ("/blog/gazin-premia-colaboradores", "Gazin premia colaboradores com 25 anos de casa")),
        "https://www.tigre.com.br/tigre-na-midia": html_de(
            ("https://x.com/a", "Tigre lança linha antiga de tubos"),
            ("https://jornal.com/b", "Multinacional de Joinville abre 200 vagas na fábrica")),
        "https://economia.exemplo/": html_de(
            ("/a", "Indústria catarinense cresce no trimestre"),
            ("/b", "Grupo Tigre investe R$ 200 milhões em nova fábrica"),
            ("/c", "Tigre vence o Criciúma em clássico de tubos e saneamento"),
            ("/d", "Tigre amplia rede de saneamento no Nordeste"),
            ("/e", "Empresas de energia discutem leilão de transmissão")),
    }
    with mock.patch.object(paginas.fontes, "leitura", lambda est: LISTA):
        p1, rel1, vistas = paginas.vigia(ESTADO, {}, LeitorFalso(noite1), "2026-10-05", REGISTRO)
        confere("primeira noite é linha de base, sem pistas", p1 == [], str(p1))
        confere("linha de base registrada", all(r["status"] in ("linha_de_base", "http_403") for r in rel1),
                str([r["status"] for r in rel1]))
        confere("página recusada aparece como recusada",
                any(r["url"] == "https://ccee.org.br" and r["status"] == "http_403" for r in rel1))

        p2, rel2, _ = paginas.vigia(ESTADO, vistas, LeitorFalso(noite2), "2026-10-06", REGISTRO)
        tit = {c["titulo"]: c for c in p2}
        confere("link novo na seção de notícias do site do cliente vira pista",
                "Sesc DF anuncia nova diretora regional" in tit, str(list(tit)))
        confere("link já visto não volta", "Sesc DF promove festival de teatro no Gama" not in tit)
        confere("link já publicado no jornal não volta",
                "Sesc DF abre inscrições para a corrida do comerciário" not in tit)
        confere("raiz do site: link novo sem cara de notícia e sem o nome fica fora",
                "Oficina de pintura em aquarela para iniciantes" not in tit
                and "Fogão 5 bocas com acendimento automático" not in tit, str(list(tit)))
        confere("raiz do site: link novo do blog com o nome entra",
                "Gazin premia colaboradores com 25 anos de casa" in tit)
        confere("sala de imprensa curada: todo link novo é do cliente, mesmo sem o nome",
                tit.get("Multinacional de Joinville abre 200 vagas na fábrica", {}).get("cliente_id") == "tigre")
        confere("veículo de terceiros: termo do registro casa",
                tit.get("Grupo Tigre investe R$ 200 milhões em nova fábrica", {}).get("onde") == "titulo")
        confere("veículo de terceiros: exclusão do cliente vale",
                "Tigre vence o Criciúma em clássico de tubos e saneamento" not in tit)
        confere("veículo de terceiros: nome ambíguo com contexto casa",
                "Tigre amplia rede de saneamento no Nordeste" in tit)
        confere("veículo de terceiros: link sem cliente fica fora",
                "Empresas de energia discutem leilão de transmissão" not in tit)
        confere("pista de gente é reconhecida",
                tit.get("Sesc DF anuncia nova diretora regional", {}).get("pauta") == "gente")
        confere("menu, mailto, imagem e 'saiba mais' não viram manchete",
                not any(t.startswith(("Fale conosco", "Escreva", "Foto", "Saiba")) for t in tit))

        # robots.txt que não respondeu não é proibição
        class LeitorRobotsMudo(LeitorFalso):
            robots = {"https://sescdf.com.br": False}

            def permite(self, url):
                return not url.startswith("https://sescdf.com.br")
        _, rel3, _ = paginas.vigia(ESTADO, vistas, LeitorRobotsMudo(noite2), "2026-10-06", REGISTRO)
        st = {r["url"]: r["status"] for r in rel3}
        confere("robots.txt sem resposta não é tratado como proibição",
                st["https://sescdf.com.br"] == "robots_sem_resposta", str(st))
        confere("página que lia bem e falhou guarda o status anterior",
                [r["antes"] for r in rel3 if r["url"] == "https://sescdf.com.br"] == ["linha_de_base"])

    print()
    print("todos os testes passaram." if not falhas else "%d teste(s) falharam." % falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(roda())
