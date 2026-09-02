#!/usr/bin/env python3
"""
Confere se a edição do dia foi realmente coletada, antes de publicar.

Existe por causa de um incidente real: em 29/08/2026 o disparo automático
terminou em 56 segundos, não pesquisou nada, não publicou edição nenhuma e
mesmo assim foi registrado como SUCCEEDED. Uma execução curta que se declara
bem-sucedida é o pior resultado possível deste projeto, porque ninguém
percebe — o jornal simplesmente mostra a notícia de ontem.

Este script é o portão. Ele falha em voz alta e com código de saída 1.

Uso:
    python3 tools/valida_edicao.py <estado.html|estado.json>

Exige que a edição na posição 0 traga um bloco "cobertura":
    "cobertura": {
      "clientes_varridos": 31,
      "buscas": 188,
      "clientes_silenciosos": 28,
      "segunda_passada_buscas": 42,
      "iniciado_em":  "2026-09-02T06:36:11-03:00",
      "concluido_em": "2026-09-02T06:52:40-03:00"
    }

A segunda passada existe porque em 01/09/2026 a coleta voltou com 3 itens de
31 clientes — e SEBRAE/BA e SEBRAE/MG, os dois maiores produtores do
histórico, vieram vazios. Uma varredura só, com uma formulação de busca só,
deixa muito na mesa. O validador não pode exigir notícia (dia quieto é
legítimo), mas pode exigir que a segunda tentativa tenha acontecido.
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
EDITORIAS = {"empresa", "setor", "gente", "risco"}

# Uma coleta honesta de 31 clientes em três camadas leva minutos, não segundos.
DURACAO_MINIMA_S = 120
# Abaixo disto não é falha — é aviso. A janela até os leitores chegarem é de
# quase uma hora, e execuções de 5 minutos vêm rendendo menos que as de 15.
DURACAO_CONFORTAVEL_S = 480
MAX_ITENS_POR_CLIENTE = 4
JANELA_DIAS = 7  # notícia muito antiga indica coleta preguiçosa ou data inventada

falhas: list[str] = []
avisos: list[str] = []


def falha(msg: str) -> None:
    falhas.append(msg)


def aviso(msg: str) -> None:
    avisos.append(msg)


def carrega(caminho: Path) -> dict:
    txt = caminho.read_text(encoding="utf8")
    if caminho.suffix.lower() == ".json":
        return json.loads(txt)
    m = re.search(r"/\*DADOS\*/(.*?)/\*FIM\*/", txt, re.S)
    if not m:
        print(f"FALHA: bloco /*DADOS*/ não encontrado em {caminho}")
        raise SystemExit(1)
    return json.loads(m.group(1))


def quando(valor: str | None):
    if not valor:
        return None
    try:
        d = datetime.fromisoformat(valor)
    except ValueError:
        return None
    return d.replace(tzinfo=TZ) if d.tzinfo is None else d


def valida(estado: dict) -> None:
    hoje = datetime.now(TZ).date()

    # --- integridade do que nunca pode ser perdido -------------------------
    if not estado.get("auth"):
        falha("o bloco 'auth' sumiu do estado — a senha de administrador seria apagada.")
    clientes = estado.get("clientes") or []
    if not clientes:
        falha("a carteira de clientes está vazia — o estado foi corrompido.")

    ativos = [c for c in clientes if c.get("ativo") is not False]
    ids = {c.get("id") for c in clientes}

    edicoes = estado.get("edicoes") or []
    if not edicoes:
        falha("nenhuma edição no estado.")
        return

    ed = edicoes[0]

    # --- a edição é mesmo de hoje? -----------------------------------------
    if ed.get("data") != hoje.isoformat():
        falha(
            f"a edição na posição 0 é de {ed.get('data')}, não de hoje ({hoje.isoformat()}). "
            "O jornal continuaria mostrando a edição anterior."
        )

    if len(edicoes) > 1 and edicoes[1].get("data") == ed.get("data"):
        falha("há duas edições com a mesma data — a de hoje deveria substituir, não duplicar.")

    # --- a coleta aconteceu de verdade? ------------------------------------
    cob = ed.get("cobertura")
    if not isinstance(cob, dict):
        falha(
            "a edição não tem o bloco 'cobertura'. Sem ele não há como provar que a coleta "
            "aconteceu — registre clientes_varridos, buscas, iniciado_em e concluido_em."
        )
    else:
        varridos = cob.get("clientes_varridos")
        if not isinstance(varridos, int):
            falha("cobertura.clientes_varridos ausente ou não é um número inteiro.")
        elif varridos < len(ativos):
            falha(
                f"a coleta cobriu {varridos} de {len(ativos)} clientes ativos. "
                "Todo cliente ativo precisa passar pelas duas camadas de busca."
            )

        buscas = cob.get("buscas")
        if not isinstance(buscas, int):
            falha("cobertura.buscas ausente ou não é um número inteiro.")
        elif buscas < len(ativos):
            falha(
                f"apenas {buscas} buscas para {len(ativos)} clientes ativos — "
                "menos de uma por cliente. O PASSO 2 foi pulado."
            )
        elif buscas < 2 * len(ativos):
            aviso(
                f"{buscas} buscas para {len(ativos)} clientes: a camada (b), de varredura na "
                "grande imprensa, provavelmente não foi feita para todos."
            )

        # A segunda passada é sobre ESFORÇO, não sobre resultado: um dia quieto
        # continua válido, mas ter tentado uma vez só não.
        silenciosos = cob.get("clientes_silenciosos")
        segunda = cob.get("segunda_passada_buscas")
        if not isinstance(silenciosos, int):
            falha(
                "cobertura.clientes_silenciosos ausente. Depois da primeira varredura, conte "
                "quantos clientes ativos ficaram sem nenhum item e registre aqui."
            )
        elif silenciosos > 0:
            if not isinstance(segunda, int):
                falha(
                    f"{silenciosos} clientes ficaram silenciosos e cobertura.segunda_passada_buscas "
                    "não foi registrado. A segunda passada sobre os silenciosos é obrigatória."
                )
            elif segunda < silenciosos:
                falha(
                    f"a segunda passada fez {segunda} buscas para {silenciosos} clientes silenciosos "
                    "— menos de uma por cliente. Volte ao PASSO 2, reformule as buscas desses "
                    "clientes (razão social, site oficial, nome + veículo do dossiê) e tente de novo."
                )

        ini, fim = quando(cob.get("iniciado_em")), quando(cob.get("concluido_em"))
        if ini is None or fim is None:
            falha("cobertura.iniciado_em / concluido_em ausentes ou em formato inválido.")
        else:
            dur = (fim - ini).total_seconds()
            if dur < DURACAO_MINIMA_S:
                falha(
                    f"a coleta durou {dur:.0f}s. Uma varredura real de {len(ativos)} clientes "
                    f"leva minutos; abaixo de {DURACAO_MINIMA_S}s a execução não pesquisou nada. "
                    "Foi exatamente assim que o incidente de 29/08/2026 passou despercebido."
                )
            elif dur < DURACAO_CONFORTAVEL_S:
                aviso(
                    f"a coleta durou {dur/60:.1f} min. Há quase uma hora de janela antes dos "
                    "leitores chegarem, e as execuções mais longas renderam bem mais: 15 min "
                    "deram 19 itens, 5 min deram 3. Não há prêmio por terminar cedo."
                )

    # --- os itens são plausíveis? ------------------------------------------
    itens = ed.get("itens") or []
    vistos_agora: dict[str, int] = {}
    por_cliente: dict[str, int] = {}
    setor_por_cliente: dict[str, int] = {}

    urls_antigas = {
        it.get("url")
        for antiga in edicoes[1:]
        for it in (antiga.get("itens") or [])
        if it.get("url")
    }

    for i, it in enumerate(itens):
        onde = f"item {i + 1}"
        cid = it.get("cliente_id")
        if cid not in ids:
            falha(f"{onde}: cliente_id '{cid}' não existe na carteira.")
        if it.get("editoria") not in EDITORIAS:
            falha(f"{onde}: editoria '{it.get('editoria')}' inválida.")
        if not (it.get("titulo") or "").strip():
            falha(f"{onde}: título vazio.")

        url = (it.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            falha(f"{onde}: url ausente ou inválida ('{url}').")
        else:
            vistos_agora[url] = vistos_agora.get(url, 0) + 1
            if url in urls_antigas:
                falha(f"{onde}: url já publicada numa edição anterior — {url}")

        d = quando(it.get("data"))
        if d is None:
            falha(f"{onde}: data '{it.get('data')}' inválida.")
        else:
            dd = d.date()
            if dd > hoje:
                falha(f"{onde}: data {dd} está no futuro.")
            elif dd < hoje - timedelta(days=JANELA_DIAS):
                aviso(f"{onde}: notícia de {dd}, fora da janela de {JANELA_DIAS} dias.")

        if cid:
            por_cliente[cid] = por_cliente.get(cid, 0) + 1
            if it.get("editoria") == "setor":
                setor_por_cliente[cid] = setor_por_cliente.get(cid, 0) + 1

    for url, n in vistos_agora.items():
        if n > 1:
            falha(f"a mesma url aparece {n} vezes nesta edição — {url}")

    for cid, n in por_cliente.items():
        if n > MAX_ITENS_POR_CLIENTE:
            falha(f"cliente '{cid}' com {n} itens (máximo {MAX_ITENS_POR_CLIENTE}).")

    for cid, n in setor_por_cliente.items():
        if n > 1:
            falha(f"cliente '{cid}' com {n} itens de editoria 'setor' (máximo 1).")

    # Edição vazia é resultado legítimo — fim de semana costuma ser assim.
    if not itens:
        aviso("edição sem nenhuma notícia. É um resultado válido, mas confira se as buscas rodaram.")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)

    estado = carrega(Path(sys.argv[1]))
    valida(estado)

    for a in avisos:
        print(f"aviso: {a}")

    if falhas:
        print()
        print(f"FALHA: a edição não passou na validação ({len(falhas)} problema(s)).")
        for f in falhas:
            print(f"  - {f}")
        print()
        print("Não publique. Corrija e rode de novo.")
        raise SystemExit(1)

    ed = (estado.get("edicoes") or [{}])[0]
    cob = ed.get("cobertura") or {}
    print(f"ok  edição {ed.get('data')} · {len(ed.get('itens') or [])} itens")
    print(f"    cobertura: {cob.get('clientes_varridos')} clientes · {cob.get('buscas')} buscas")
    if isinstance(cob.get("clientes_silenciosos"), int):
        print(f"    segunda passada: {cob.get('segunda_passada_buscas', 0)} buscas "
              f"sobre {cob['clientes_silenciosos']} clientes silenciosos")
    camadas = cob.get("itens_por_camada")
    if isinstance(camadas, dict) and camadas:
        # Telemetria opcional: de onde vieram os itens. Serve para medir qual
        # camada rende e qual so gasta orcamento — nao e exigida.
        print("    itens por camada: " + ", ".join(f"{k}={v}" for k, v in camadas.items()))
    if avisos:
        print(f"    {len(avisos)} aviso(s) acima, nenhum bloqueante.")


if __name__ == "__main__":
    main()
