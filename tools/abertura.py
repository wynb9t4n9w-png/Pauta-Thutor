#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apura a abertura da Pauta Thutor: tempo em Americana e indicadores de mercado.

    python3 tools/abertura.py            resumo legível + bloco JSON
    python3 tools/abertura.py --json     só o JSON, para colar na edição

A saída tem duas chaves independentes, "tempo" e "mercado", que a coleta copia
para dentro do objeto da edição. As duas são opcionais: o validador não exige
nenhuma delas, porque uma API fora do ar não pode derrubar a edição do dia.

Fontes, todas públicas e sem cadastro:

  tempo    Open-Meteo — previsão do dia para Americana/SP, sede da Thutor.
  câmbio   Banco Central do Brasil — séries SGS 1 (dólar venda) e 21619 (euro
           venda). É a PTAX, taxa oficial; não é cotação de casa de câmbio.
  ações    Yahoo Finance (chart API), fechamento do pregão.

Cada indicador é apurado de forma independente: se uma fonte cair, aquele
indicador não entra e os outros seguem.

Só entram ações de clientes de capital aberto. O mapa está aqui embaixo, e não
na carteira, para que a coleta diária nunca precise escrever em
estado["clientes"].
"""

import json
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta

TEMPO_LIMITE = 25
JANELA_DIAS = 30

# Sede da Thutor.
CIDADE = {"nome": "Americana/SP", "lat": -22.7392, "lon": -47.3312}

# Clientes de capital aberto: cliente_id -> (ticker Yahoo, rótulo, o que é o papel)
ACOES = {
    "cemig": ("CMIG4.SA", "CMIG4", "Cemig · ação preferencial"),
    "taesa": ("TAEE11.SA", "TAEE11", "Taesa · unit"),
}

# Faixa de estabilidade por tipo: abaixo dela a variação em 30 dias é ruído.
# Câmbio oscila menos que ação, então a régua é mais curta.
BANDA = {"cambio": 1.5, "acao": 3.0}

# Códigos WMO da Open-Meteo -> (texto, ícone desenhado na página)
TEMPO_WMO = {
    0: ("Céu limpo", "sol"),
    1: ("Sol com poucas nuvens", "sol"),
    2: ("Parcialmente nublado", "sol-nuvem"),
    3: ("Nublado", "nuvem"),
    45: ("Névoa", "nevoa"), 48: ("Nevoeiro", "nevoa"),
    51: ("Garoa fraca", "chuva"), 53: ("Garoa", "chuva"), 55: ("Garoa forte", "chuva"),
    56: ("Garoa congelante", "chuva"), 57: ("Garoa congelante", "chuva"),
    61: ("Chuva fraca", "chuva"), 63: ("Chuva", "chuva"), 65: ("Chuva forte", "chuva"),
    66: ("Chuva congelante", "chuva"), 67: ("Chuva congelante", "chuva"),
    71: ("Neve fraca", "neve"), 73: ("Neve", "neve"), 75: ("Neve forte", "neve"),
    77: ("Grãos de neve", "neve"),
    80: ("Pancadas isoladas", "chuva"), 81: ("Pancadas de chuva", "chuva"),
    82: ("Pancadas fortes", "chuva"),
    85: ("Pancadas de neve", "neve"), 86: ("Pancadas de neve", "neve"),
    95: ("Trovoadas", "tempestade"),
    96: ("Trovoadas com granizo", "tempestade"), 99: ("Trovoadas com granizo", "tempestade"),
}


def baixar(url):
    """Devolve o corpo da resposta. Tenta urllib e cai para o curl do sistema."""
    req = urllib.request.Request(url, headers={"User-Agent": "PautaThutor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as r:
            return r.read().decode("utf-8")
    except Exception:
        saida = subprocess.run(
            ["curl", "-sS", "--max-time", str(TEMPO_LIMITE),
             "-H", "User-Agent: PautaThutor/1.0", url],
            capture_output=True, text=True,
        )
        if saida.returncode != 0 or not saida.stdout.strip():
            raise RuntimeError((saida.stderr or "resposta vazia").strip()[:200])
        return saida.stdout


# ---------------------------------------------------------------- tempo

def previsao():
    """Previsão do dia para a sede. Levanta exceção se a fonte não responder."""
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
           "precipitation_probability_max,sunrise,sunset"
           "&timezone=America%%2FSao_Paulo&forecast_days=1"
           % (CIDADE["lat"], CIDADE["lon"]))
    d = json.loads(baixar(url)).get("daily") or {}
    if not d.get("time"):
        raise RuntimeError("previsão sem dados diários")

    codigo = int((d.get("weather_code") or [0])[0])
    condicao, icone = TEMPO_WMO.get(codigo, ("Tempo instável", "nuvem"))
    chuva = (d.get("precipitation_probability_max") or [None])[0]

    return {
        "cidade": CIDADE["nome"],
        "data": d["time"][0],
        "condicao": condicao,
        "icone": icone,
        "codigo": codigo,
        "max": round(float(d["temperature_2m_max"][0])),
        "min": round(float(d["temperature_2m_min"][0])),
        "chuva_pct": None if chuva is None else int(chuva),
        "nascer": (d.get("sunrise") or [""])[0][-5:],
        "por": (d.get("sunset") or [""])[0][-5:],
        "fonte": "Open-Meteo",
    }


# ---------------------------------------------------------------- mercado

def serie_bcb(codigo):
    """Série do SGS: devolve [(date, valor)] em ordem cronológica.

    Pelo intervalo de datas, e não por "últimos N": esse atalho do SGS tem teto
    de 20 valores, menos que os pregões de 30 dias corridos.
    """
    fim = date.today()
    inicio = fim - timedelta(days=JANELA_DIAS + 20)  # folga para feriados
    url = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json"
           "&dataInicial=%s&dataFinal=%s"
           % (codigo, inicio.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y")))
    dados = json.loads(baixar(url))
    if isinstance(dados, dict):
        raise RuntimeError(str((dados.get("erro") or {}).get("detail") or dados)[:160])
    pontos = []
    for linha in dados:
        d = datetime.strptime(linha["data"], "%d/%m/%Y").date()
        pontos.append((d, float(linha["valor"])))
    pontos.sort()
    return pontos


def serie_yahoo(ticker):
    """Fechamentos diários do Yahoo: devolve [(date, valor)] cronológico."""
    erro = None
    for host in ("query1", "query2"):
        url = ("https://%s.finance.yahoo.com/v8/finance/chart/%s"
               "?range=3mo&interval=1d" % (host, ticker))
        try:
            dados = json.loads(baixar(url))
        except Exception as e:  # host fora do ar, resposta truncada
            erro = e
            continue
        resultado = (dados.get("chart") or {}).get("result") or []
        if not resultado:
            erro = RuntimeError((dados.get("chart") or {}).get("error") or "sem dados")
            continue
        bloco = resultado[0]
        marcas = bloco.get("timestamp") or []
        fechos = ((bloco.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        pontos = [(datetime.fromtimestamp(t).date(), float(v))
                  for t, v in zip(marcas, fechos) if v is not None]
        if pontos:
            pontos.sort()
            return pontos
        erro = RuntimeError("série sem fechamentos")
    raise RuntimeError(str(erro))


def variacao(de, para):
    return None if not de else round((para / de - 1) * 100, 2)


def monta(id_, rotulo, detalhe, fonte, tipo, casas, pontos):
    """Transforma a série bruta no indicador que a capa exibe."""
    if len(pontos) < 2:
        raise RuntimeError("série curta demais para comparar")

    fim = pontos[-1][0]
    janela = [(d, v) for d, v in pontos if d >= fim - timedelta(days=JANELA_DIAS)]
    if len(janela) < 2:
        janela = pontos[-2:]

    valores = [v for _, v in janela]
    atual = valores[-1]
    var_30d = variacao(valores[0], atual)
    banda = BANDA[tipo]
    tendencia = "estavel"
    if var_30d is not None and var_30d >= banda:
        tendencia = "alta"
    elif var_30d is not None and var_30d <= -banda:
        tendencia = "baixa"

    return {
        "id": id_,
        "rotulo": rotulo,
        "detalhe": detalhe,
        "fonte": fonte,
        "tipo": tipo,
        "casas": casas,
        "data": fim.isoformat(),
        "valor": round(atual, casas),
        "var_dia": variacao(pontos[-2][1], atual),
        "var_30d": var_30d,
        "min_30d": round(min(valores), casas),
        "max_30d": round(max(valores), casas),
        "pregoes_30d": len(janela),
        "tendencia": tendencia,
        "serie": [round(v, casas) for v in valores],
    }


def mercado():
    """Devolve (bloco, falhas). O bloco é None se nada foi apurado."""
    indicadores, falhas = [], []

    for id_, rotulo, detalhe, codigo in (
        ("usd", "Dólar", "USD/BRL · PTAX venda", 1),
        ("eur", "Euro", "EUR/BRL · PTAX venda", 21619),
    ):
        try:
            indicadores.append(monta(id_, rotulo, detalhe, "Banco Central",
                                     "cambio", 4, serie_bcb(codigo)))
        except Exception as e:
            falhas.append("%s: %s" % (rotulo, e))

    for cliente_id, (ticker, rotulo, detalhe) in ACOES.items():
        try:
            ind = monta(cliente_id, rotulo, detalhe, "Yahoo Finance",
                        "acao", 2, serie_yahoo(ticker))
            ind["cliente_id"] = cliente_id
            indicadores.append(ind)
        except Exception as e:
            falhas.append("%s: %s" % (rotulo, e))

    if not indicadores:
        return None, falhas
    bloco = {
        "apurado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "indicadores": indicadores,
    }
    if falhas:
        bloco["falhas"] = falhas
    return bloco, falhas


def coletar():
    saida, falhas = {}, []

    try:
        saida["tempo"] = previsao()
    except Exception as e:
        falhas.append("Tempo: %s" % e)

    bloco, falhas_mercado = mercado()
    if bloco:
        saida["mercado"] = bloco
    falhas.extend(falhas_mercado)
    return saida, falhas


def main():
    so_json = "--json" in sys.argv[1:]
    saida, falhas = coletar()

    if not saida:
        sys.stderr.write("nada apurado:\n  " + "\n  ".join(falhas) + "\n")
        sys.stderr.write("Publique a edição sem a abertura — ela é opcional.\n")
        return 1

    if so_json:
        print(json.dumps(saida, ensure_ascii=False))
        return 0

    t = saida.get("tempo")
    if t:
        print("tempo    %s, %s · máx %d° / mín %d° · chuva %s"
              % (t["cidade"], t["condicao"].lower(), t["max"], t["min"],
                 "—" if t["chuva_pct"] is None else str(t["chuva_pct"]) + "%"))
    seta = {"alta": "▲", "baixa": "▼", "estavel": "="}
    for i in (saida.get("mercado") or {}).get("indicadores", []):
        print("  %-8s %10.*f  em %s   dia %+.2f%%   30d %+.2f%%  %s %s"
              % (i["rotulo"], i["casas"], i["valor"],
                 "/".join(reversed(i["data"].split("-")[1:])),
                 i["var_dia"] or 0, i["var_30d"] or 0,
                 seta[i["tendencia"]], i["tendencia"]))
    if falhas:
        print("\nfalharam (a abertura vai sem eles):")
        for f in falhas:
            print("  " + f)
    print("\nchaves para juntar ao objeto da edição:\n")
    print(json.dumps(saida, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
