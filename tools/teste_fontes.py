#!/usr/bin/env python3
"""Testes da lista de leitura direta do dossiê (tools/fontes.py), sem rede.

    python3 tools/teste_fontes.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fontes  # noqa: E402

falhas = 0


def confere(nome, cond, detalhe=""):
    global falhas
    print(("ok    " if cond else "FALHA ") + nome + ("" if cond else "  " + detalhe))
    falhas += 0 if cond else 1


def item(cid, url):
    return {"cliente_id": cid, "url": url, "fonte": url, "titulo": "t"}


def roda():
    tmp = Path(tempfile.mkdtemp())
    feeds = tmp / "feeds.json"
    feeds.write_text(json.dumps({"feeds": [{"nome": "ASN", "url": "https://agenciasebrae.com.br/feed/"}]}))
    extras = tmp / "complementares.json"
    extras.write_text(json.dumps({"clientes": {
        "rocha": {"paginas": [{"url": "https://www.rochalog.com.br/news/", "tipo": "sala de imprensa"}]}}}))
    estado = {
        "clientes": [
            {"id": "rocha", "nome": "ROCHA", "site": "rochalog.com.br"},
            {"id": "ccee", "nome": "CCEE", "site": "ccee.org.br"},
            {"id": "coop", "nome": "COOPLIVRE", "site": "sicoob.com.br/web/sicoobcooplivre"},
            {"id": "eng", "nome": "ENGECRED", "site": ""},
            {"id": "sebrae", "nome": "SEBRAE", "site": ""},
            {"id": "parado", "nome": "PARADO", "site": "parado.com.br", "ativo": False},
        ],
        "edicoes": [{"data": "2026-10-01", "itens":
            [item("sebrae", "https://agenciasebrae.com.br/a%d" % i) for i in range(5)]
            + [item("ccee", "https://www.otempo.com.br/x%d" % i) for i in range(3)]
            + [item("ccee", "https://raro.com.br/y%d" % i) for i in range(2)]
            + [item("ccee", "https://www.infomoney.com.br/z%d" % i) for i in range(4)]
            + [item("eng", "https://www.sicoob.com.br/web/sicoobengecred/n%d" % i) for i in range(4)]}],
    }
    ler = fontes.leitura(estado, feeds, extras)
    urls = [pg["url"] for pg in ler]
    hosts = [fontes._host(u) for u in urls]

    confere("domínio lido por feed fica fora", "agenciasebrae.com.br" not in hosts, str(urls))
    confere("página de imprensa curada substitui a raiz do site",
            "https://www.rochalog.com.br/news/" in urls and "https://rochalog.com.br" not in urls, str(urls))
    confere("site do cliente entra", "https://ccee.org.br" in urls, str(urls))
    confere("veículo com 3 notícias entra", "https://otempo.com.br/" in urls, str(urls))
    confere("veículo com 2 notícias fica fora", "raro.com.br" not in hosts, str(urls))
    confere("grande imprensa fica fora (camada b)", "infomoney.com.br" not in hosts, str(urls))
    confere("raiz de host já listado por caminho próprio não entra de novo",
            urls.count("https://sicoob.com.br/") == 0 and hosts.count("sicoob.com.br") == 1, str(urls))
    confere("cliente inativo fica fora", "parado.com.br" not in hosts, str(urls))

    print()
    print("todos os testes passaram." if not falhas else "%d teste(s) falharam." % falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(roda())
