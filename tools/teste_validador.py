#!/usr/bin/env python3
"""
Testes do validador de edição.

Roda tools/valida_edicao.py contra cenários sintéticos e confere o código de
saída de cada um. O caso "incidente-56s" reproduz o disparo de 29/08/2026 que
terminou em 56 segundos sem pesquisar nada e ainda assim foi registrado como
bem-sucedido — é o teste que existe para essa falha nunca mais passar calada.

Uso:
    python3 tools/teste_validador.py
"""

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
RAIZ = Path(__file__).resolve().parent.parent
VALIDADOR = RAIZ / "tools" / "valida_edicao.py"

agora = datetime.now(TZ)
hoje = agora.date()


def base() -> dict:
    return {
        "versao": 1,
        "auth": {"usuario": "admin", "salt": "s", "hash": "h"},
        "clientes": [{"id": f"c{i}", "nome": f"C{i}", "ativo": True} for i in range(31)],
        "edicoes": [],
    }


def edicao(n_itens: int = 3, **cobertura) -> dict:
    cob = {
        "clientes_varridos": 31,
        "buscas": 62,
        "clientes_silenciosos": 28,
        "segunda_passada_buscas": 42,
        "iniciado_em": (agora - timedelta(minutes=11)).isoformat(),
        "concluido_em": agora.isoformat(),
    }
    cob.update(cobertura)
    # None significa "remova esta chave" — serve para testar campo ausente.
    cob = {k: v for k, v in cob.items() if v is not None}
    return {
        "data": hoje.isoformat(),
        "cobertura": cob,
        "itens": [
            {
                "cliente_id": f"c{i}",
                "editoria": "empresa",
                "titulo": f"Título {i}",
                "resumo": "Resumo.",
                "fonte": "Veículo",
                "url": f"https://exemplo.com/{i}",
                "data": hoje.isoformat(),
            }
            for i in range(n_itens)
        ],
    }


def sem_cobertura() -> dict:
    return {k: v for k, v in edicao().items() if k != "cobertura"}


def abertura(**troca) -> dict:
    """Uma faixa de abertura íntegra, com os campos que a página lê."""
    ind = {
        "id": "usd", "rotulo": "Dólar", "detalhe": "USD/BRL · PTAX venda",
        "fonte": "Banco Central", "tipo": "cambio", "casas": 4,
        "data": hoje.isoformat(), "valor": 5.1253, "var_dia": 0.57, "var_30d": 0.19,
        "min_30d": 5.0908, "max_30d": 5.2236, "tendencia": "estavel",
        "serie": [5.1, 5.12, 5.1253],
    }
    ind.update(troca)
    ind = {k: v for k, v in ind.items() if v is not None}
    return {
        "tempo": {
            "cidade": "Americana/SP", "data": hoje.isoformat(), "condicao": "Nublado",
            "icone": "nuvem", "max": 30, "min": 15, "chuva_pct": 21, "fonte": "Open-Meteo",
        },
        "mercado": {"apurado_em": agora.isoformat(), "indicadores": [ind]},
    }


def item(cid: str, url: str, titulo: str, data: str | None = None) -> dict:
    return {"cliente_id": cid, "editoria": "empresa", "titulo": titulo, "resumo": "",
            "fonte": "Veículo", "url": url, "data": data or hoje.isoformat()}


def url_repetida() -> dict:
    it = lambda cid: {  # noqa: E731
        "cliente_id": cid, "editoria": "empresa", "titulo": "T", "resumo": "",
        "fonte": "F", "url": "https://exemplo.com/mesma", "data": hoje.isoformat(),
    }
    return {**edicao(), "itens": [it("c0"), it("c1")]}


# (nome, estado, código de saída esperado)
CASOS = [
    ("edição saudável", {**base(), "edicoes": [edicao()]}, 0),
    ("edição vazia (fim de semana)", {**base(), "edicoes": [edicao(0)]}, 0),
    (
        "incidente 56s — não pesquisou nada",
        {
            **base(),
            "edicoes": [
                edicao(
                    clientes_varridos=0,
                    buscas=0,
                    iniciado_em=(agora - timedelta(seconds=56)).isoformat(),
                    concluido_em=agora.isoformat(),
                )
            ],
        },
        1,
    ),
    ("cobertura parcial (18 de 31)", {**base(), "edicoes": [edicao(clientes_varridos=18)]}, 1),
    ("sem bloco de cobertura", {**base(), "edicoes": [sem_cobertura()]}, 1),
    (
        "edição é de ontem",
        {**base(), "edicoes": [{**edicao(), "data": (hoje - timedelta(days=1)).isoformat()}]},
        1,
    ),
    ("url duplicada na mesma edição", {**base(), "edicoes": [url_repetida()]}, 1),
    (
        "auth apagado",
        {**{k: v for k, v in base().items() if k != "auth"}, "edicoes": [edicao()]},
        1,
    ),
    (
        "sem segunda passada",
        {**base(), "edicoes": [edicao(segunda_passada_buscas=None)]},
        1,
    ),
    (
        "segunda passada rala (5 buscas / 28 silenciosos)",
        {**base(), "edicoes": [edicao(segunda_passada_buscas=5)]},
        1,
    ),
    (
        "sem contagem de silenciosos",
        {**base(), "edicoes": [edicao(clientes_silenciosos=None)]},
        1,
    ),
    (
        "dia sem silenciosos dispensa segunda passada",
        {**base(), "edicoes": [edicao(clientes_silenciosos=0, segunda_passada_buscas=None)]},
        0,
    ),
    # --- a mesma pauta por outro caminho (estudo de 30/09/2026) --------------
    (
        "mesma url com acento codificado já publicada ontem",
        {**base(), "edicoes": [
            {**edicao(0), "itens": [item("c1", "https://sesc.df/corrida-do-comerci%C3%A1rio/", "Corrida")]},
            {**edicao(0), "data": (hoje - timedelta(days=1)).isoformat(),
             "itens": [item("c1", "https://sesc.df/corrida-do-comerciário", "Corrida",
                            (hoje - timedelta(days=1)).isoformat())]},
        ]},
        1,
    ),
    (
        "mesmo título, outro veículo, 3 dias antes",
        {**base(), "edicoes": [
            {**edicao(0), "itens": [item("c1", "https://jornal.com/forum", "Fórum de Negócios conecta empresas a novos mercados")]},
            {**edicao(0), "data": (hoje - timedelta(days=3)).isoformat(),
             "itens": [item("c1", "https://agencia.com/forum", "Fórum de Negócios conecta empresas a novos mercados",
                            (hoje - timedelta(days=3)).isoformat())]},
        ]},
        1,
    ),
    (
        "mesmo título há 20 dias não é repetição",
        {**base(), "edicoes": [
            {**edicao(0), "itens": [item("c1", "https://jornal.com/forum2", "Fórum de Negócios conecta empresas a novos mercados")]},
            {**edicao(0), "data": (hoje - timedelta(days=20)).isoformat(),
             "itens": [item("c1", "https://agencia.com/forum2", "Fórum de Negócios conecta empresas a novos mercados",
                            (hoje - timedelta(days=20)).isoformat())]},
        ]},
        0,
    ),
    (
        "pauta parecida é aviso, não falha",
        {**base(), "edicoes": [
            {**edicao(0), "itens": [item("c1", "https://a.com/1", "Assembleia elege Elisa Bastos para diretoria da CCEE")]},
            {**edicao(0), "data": (hoje - timedelta(days=1)).isoformat(),
             "itens": [item("c1", "https://b.com/1", "Em Assembleia, agentes da CCEE elegem Elisa Bastos como nova diretora",
                            (hoje - timedelta(days=1)).isoformat())]},
        ]},
        0,
    ),
    ("esforço de busca baixo é aviso, não falha", {**base(), "edicoes": [edicao(buscas=100)]}, 0),

    # --- faixa de abertura: opcional, mas íntegra quando vem ----------------
    (
        "abertura completa (tempo + mercado)",
        {**base(), "edicoes": [{**edicao(), **abertura()}]},
        0,
    ),
    (
        "sem abertura nenhuma (API fora do ar)",
        {**base(), "edicoes": [edicao()]},
        0,
    ),
    (
        "indicador sem valor de fechamento",
        {**base(), "edicoes": [{**edicao(), **abertura(valor=None)}]},
        1,
    ),
    (
        "indicador com tendência inventada",
        {**base(), "edicoes": [{**edicao(), **abertura(tendencia="subindo")}]},
        1,
    ),
    (
        "série curta demais para o gráfico",
        {**base(), "edicoes": [{**edicao(), **abertura(serie=[5.1])}]},
        1,
    ),
    (
        "fechamento com data no futuro",
        {
            **base(),
            "edicoes": [{**edicao(), **abertura(data=(hoje + timedelta(days=1)).isoformat())}],
        },
        1,
    ),
    (
        "previsão do tempo sem temperatura",
        {
            **base(),
            "edicoes": [{
                **edicao(),
                "tempo": {"cidade": "Americana/SP", "data": hoje.isoformat(),
                          "condicao": "Nublado", "icone": "nuvem", "min": 15},
            }],
        },
        1,
    ),
    (
        "previsão de ontem é aviso, não falha",
        {
            **base(),
            "edicoes": [{
                **edicao(),
                "tempo": {"cidade": "Americana/SP", "data": (hoje - timedelta(days=1)).isoformat(),
                          "condicao": "Nublado", "icone": "nuvem", "max": 28, "min": 14},
            }],
        },
        0,
    ),
    (
        "cliente_id inexistente",
        {
            **base(),
            "edicoes": [
                {**edicao(), "itens": [{
                    "cliente_id": "fantasma", "editoria": "empresa", "titulo": "T",
                    "resumo": "", "fonte": "F", "url": "https://exemplo.com/1",
                    "data": hoje.isoformat(),
                }]},
            ],
        },
        1,
    ),
]


def main() -> None:
    if not VALIDADOR.exists():
        raise SystemExit(f"validador não encontrado em {VALIDADOR}")

    largura = max(len(n) for n, _, _ in CASOS)
    falhou = 0

    with tempfile.TemporaryDirectory() as tmp:
        for nome, estado, esperado in CASOS:
            caminho = Path(tmp) / "estado.json"
            caminho.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf8")
            r = subprocess.run(
                [sys.executable, str(VALIDADOR), str(caminho)],
                capture_output=True, text=True,
            )
            ok = r.returncode == esperado
            falhou += not ok
            marca = "ok  " if ok else "FALHOU"
            print(f"{marca} {nome:<{largura}}  saída={r.returncode} esperado={esperado}")
            if not ok:
                print("     " + (r.stdout or r.stderr).strip().replace("\n", "\n     "))

    # --- recall contra os candidatos da camada (e) --------------------------
    def cand(cliente_id, url, onde="feed_proprio", **extra):
        c = {"cliente_id": cliente_id, "cliente": cliente_id.upper(), "url": url,
             "titulo": f"Pauta de {cliente_id}", "onde": onde, "nome_no_titulo": True}
        c.update(extra)
        return c

    cheio = {**edicao(0), "itens": [
        {"cliente_id": "c1", "editoria": "empresa", "titulo": f"T{k}", "resumo": "",
         "fonte": "F", "url": f"https://exemplo.com/c1-{k}", "data": hoje.isoformat()}
        for k in range(4)]}
    RECALL = [
        ("recall: candidato forte ficou de fora com vaga -> aviso",
         [edicao(3)], [cand("c9", "https://feed.com/1")], True),
        ("recall: candidato já está na edição -> sem aviso",
         [edicao(3)], [cand("c0", "https://exemplo.com/0")], False),
        ("recall: cliente já tem 4 itens -> sem aviso",
         [cheio], [cand("c1", "https://feed.com/2")], False),
        ("recall: menção só no corpo não cobra -> sem aviso",
         [edicao(3)], [cand("c9", "https://feed.com/3", onde="corpo")], False),
        ("recall: pauta da agência sem o nome e sem tema forte não cobra",
         [edicao(3)], [cand("c9", "https://feed.com/4", nome_no_titulo=False, pauta="servico")], False),
        ("recall: pauta da agência sem o nome mas de gente cobra",
         [edicao(3)], [cand("c9", "https://feed.com/5", nome_no_titulo=False, pauta="gente")], True),
        ("recall: candidato que repete pauta recente não cobra",
         [edicao(3)], [cand("c9", "https://feed.com/6", parecido_com={"data": "x", "titulo": "y"})], False),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for nome, eds, cands, espera_aviso in RECALL:
            est = Path(tmp) / "estado.json"
            cf = Path(tmp) / "candidatos.json"
            est.write_text(json.dumps({**base(), "edicoes": eds}, ensure_ascii=False), encoding="utf8")
            cf.write_text(json.dumps({"candidatos": cands}, ensure_ascii=False), encoding="utf8")
            r = subprocess.run([sys.executable, str(VALIDADOR), str(est), "--candidatos", str(cf)],
                               capture_output=True, text=True)
            avisou = "candidato(s) forte(s)" in r.stdout
            ok = r.returncode == 0 and avisou == espera_aviso
            falhou += not ok
            print(f"{'ok  ' if ok else 'FALHOU'} {nome:<{largura}}  saída={r.returncode} aviso={avisou}")
            if not ok:
                print("     " + (r.stdout or r.stderr).strip().replace("\n", "\n     "))

    total = len(CASOS) + len(RECALL)
    print()
    if falhou:
        print(f"{falhou} de {total} testes falharam.")
        raise SystemExit(1)
    print(f"{total} de {total} testes passaram.")


if __name__ == "__main__":
    main()
