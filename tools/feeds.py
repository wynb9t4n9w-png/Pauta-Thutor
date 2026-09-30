#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camada (e) da coleta: lê os feeds RSS registrados e entrega candidatos.

    python3 tools/feeds.py <estado.html|estado.json> [opções]

    --horas N          janela, em horas até agora (padrão 72)
    --ate ISO          fim da janela (padrão: agora) — para medir noites passadas
    --saida ARQ        grava os candidatos em JSON (a coleta lê daqui)
    --saude ARQ        registra a saúde de cada feed no histórico e aponta mudanças
    --registro ARQ     registro de feeds (padrão fontes/feeds.json)

POR QUE EXISTE

Até 28/09/2026 a coleta lia as fontes abrindo a página inicial de cada uma e
pedindo ao modelo que listasse as manchetes. Funcionou, mas com três fraquezas
que os números mostraram:

  - página inicial raramente traz a data de cada manchete (a da ASN não traz), e
    sem data não dá para saber se a notícia cabe na janela;
  - o modelo lê o que cabe na tela, e cada noite escolhe um pouco diferente;
  - custa tokens ler uma página inteira para aproveitar três linhas.

Feed resolve as três: cada item vem com título, link e data de publicação, e a
leitura é determinística — o script não "esquece" de olhar uma fonte.

COMO SE COMPORTA COM OS EDITORES

Feed é a porta que o próprio site deixa aberta para leitores automáticos. Em
28/09/2026, Folha de Londrina e Bem Paraná recusavam robôs na página inicial
e serviam o feed normalmente: a escolha do editor é essa, e a gente a segue.
O script:

  - se identifica honestamente, com um endereço para contato;
  - consulta o robots.txt de cada site e não busca o que ele proíbe;
  - faz uma requisição por vez, com pausa entre duas no mesmo site;
  - pagina só até alcançar o início da janela, nunca além do teto do registro.

Não se disfarça de navegador, não contorna bloqueio e não usa agregador que
proíbe o acesso no robots.txt (o RSS de busca do Google Notícias, por exemplo,
proíbe — e nomeia os robôs da Anthropic).

SAÍDA

Candidatos, não itens prontos. Cada um traz cliente, título, link, data, veículo
e o trecho que o próprio feed publicou. A coleta ainda confirma se é mesmo
sobre o cliente, classifica a editoria e escreve o resumo.
"""

import argparse
from collections import Counter
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from texto import (LIMIAR_REPETICAO, mesmo_titulo, normaliza,  # noqa: E402,F401
                   semelhanca, url_canonica)

TZ = ZoneInfo("America/Sao_Paulo")
RAIZ = Path(__file__).resolve().parent.parent
REGISTRO_PADRAO = RAIZ / "fontes" / "feeds.json"
TOKEN_ROBOTS = "PautaThutor"
TEMPO_LIMITE = 25
PAUSA_MESMO_SITE = 0.8
HISTORICO_DIAS = 60
# Feed cujo item MAIS NOVO tem mais que isto está parado: o editor deixou de
# publicar por ele. Em 30/09/2026 três feeds do registro estavam assim desde o
# cadastro (Brado, Grupo CRH e ABAC, com o último item de 2016, 2022 e 2022)
# e nenhum alerta disparou, porque os alertas só comparavam uma noite com as
# anteriores — e um feed que nunca rendeu não "passa a falhar" nem "seca".
PARADO_DIAS = 90
DIAS_REPETICAO = 10
TRECHO_MAX = 400

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


# ------------------------------------------------------------ texto e datas

def ler_data(txt):
    """Data de um item de feed, com fuso. Aceita RFC 822, ISO 8601 e o formato
    'AAAA-MM-DD HH:MM:SS' que alguns portais usam. Sem fuso, assume São Paulo."""
    txt = (txt or "").strip()
    if not txt:
        return None
    d = None
    try:
        d = parsedate_to_datetime(txt)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=TZ)


def sem_html(txt):
    txt = re.sub(r"<[^>]+>", " ", txt or "")
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()


def _padrao(termo):
    t = re.escape(normaliza(termo))
    return re.compile(r"(?<![a-z0-9])" + t + r"(?![a-z0-9])")


def casa(termos, texto):
    """Primeiro termo que aparece como palavra inteira no texto, ou None."""
    alvo = normaliza(texto)
    for termo in termos:
        if termo and _padrao(termo).search(alvo):
            return termo
    return None


# ------------------------------------------------------------ feed

def ler_feed(conteudo):
    """Itens de um RSS 2.0 ou Atom: [{titulo, url, publicado, resumo, corpo}].
    Levanta ValueError se o conteúdo não for um feed."""
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError as e:
        raise ValueError("não é XML válido (%s)" % e) from None

    itens = []
    rss = raiz.findall(".//item")
    if rss:
        for it in rss:
            itens.append({
                "titulo": sem_html(it.findtext("title")),
                "url": (it.findtext("link") or "").strip(),
                "publicado": ler_data(it.findtext("pubDate") or it.findtext("dc:date", namespaces=NS)),
                "resumo": sem_html(it.findtext("description")),
                "corpo": sem_html(it.findtext("content:encoded", namespaces=NS)),
            })
        return itens

    for en in raiz.findall("atom:entry", NS):
        link = ""
        for l in en.findall("atom:link", NS):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href", "")
                break
        itens.append({
            "titulo": sem_html(en.findtext("atom:title", namespaces=NS)),
            "url": link.strip(),
            "publicado": ler_data(en.findtext("atom:published", namespaces=NS)
                                  or en.findtext("atom:updated", namespaces=NS)),
            "resumo": sem_html(en.findtext("atom:summary", namespaces=NS)),
            "corpo": sem_html(en.findtext("atom:content", namespaces=NS)),
        })
    if not itens and raiz.tag not in ("rss", "{%s}feed" % NS["atom"]) and not raiz.tag.endswith("RDF"):
        raise ValueError("XML sem itens de feed (raiz <%s>)" % raiz.tag)
    return itens


# ------------------------------------------------------------ pauta

# Sinal, não filtro: ajuda a coleta a pôr na frente o que um consultor de
# cultura e gestão usaria numa conversa com o cliente. A decisão final é dela.
# Ordem de precedência: risco, gente, estratégia, serviço, geral.
PAUTAS = [
    ("risco", ["processo judicial", "acao judicial", "justica", "liminar", "multa", "multada",
               "multado", "autuada", "autuado", "investigacao", "investigado", "investigada",
               "denuncia", "denunciado", "denunciada", "acidente", "morte", "greve", "crise",
               "prejuizo", "rombo", "fraude", "recuperacao judicial", "falencia", "irregularidade",
               "irregularidades", "condenada", "condenado", "indenizacao", "ministerio publico",
               "policia federal", "cpi", "procon", "apagao"]),
    ("gente", ["nomeia", "nomeado", "nomeada", "nomeacao", "assume", "posse", "empossado",
               "presidente", "diretor", "diretora", "diretoria", "conselho de administracao", "ceo",
               "executivo", "executiva", "lideranca", "liderancas", "sucessao", "sucessor",
               "colaboradores", "funcionarios", "empregados", "trabalhadores", "contrata",
               "contratacao", "contratacoes", "demite", "demissao", "demissoes", "layoff",
               "trainee", "processo seletivo", "concurso", "cultura organizacional",
               "clima organizacional", "gptw", "great place to work",
               "melhores empresas para trabalhar", "diversidade", "inclusao", "inclusivas",
               "pcd", "equidade", "saude mental", "bem-estar", "bem estar", "transparencia salarial",
               "remuneracao", "plr", "universidade corporativa", "academy"]),
    ("estrategia", ["investimento", "investimentos", "investe", "investira", "aporte", "aquisicao",
                    "adquire", "fusao", "incorporacao", "joint venture", "parceria", "acordo",
                    "expansao", "expande", "inaugura", "inauguracao", "nova unidade", "novas unidades",
                    "fabrica", "resultado", "resultados", "lucro", "receita", "faturamento", "balanco",
                    "trimestre", "dividendos", "jcp", "ipo", "debentures", "reestruturacao",
                    "reorganizacao", "plano estrategico", "bilhao", "bilhoes", "ranking", "recorde",
                    "leilao", "concessao", "licitacao", "franquia", "franquias"]),
    ("servico", ["dica", "dicas", "saiba", "confira", "veja", "entenda", "como", "passo a passo",
                 "guia", "orienta", "orientacoes", "aprenda", "descubra", "ajuda", "pode", "podem",
                 "exigem", "tendencia", "tendencias", "inscricoes", "inscreva", "gratuito", "gratuita",
                 "gratuitas", "gratuitos", "curso", "oficina", "palestra", "webinar", "live"]),
]


def classifica_pauta(titulo, trecho=""):
    """Tema provável do item, pelo título; o trecho só desempata o que o título
    não diz. 'geral' quando nada se destaca."""
    for texto_ in (titulo, trecho):
        for nome, gatilhos in PAUTAS:
            if casa(gatilhos, texto_):
                return nome
    return "geral"


# ------------------------------------------------------------ carteira

def termos_do(cliente, termos_cfg):
    """Como reconhecer o cliente num feed setorial. Registro primeiro; na falta
    dele, nome e razão social."""
    if cliente["id"] in termos_cfg:
        return list(termos_cfg[cliente["id"]])
    return [t for t in (cliente.get("nome"), cliente.get("razao")) if t and len(t) >= 4]


def casa_contexto(ctx, topo):
    """Nome ambíguo ('Tigre', 'Atlas', 'Rex') só vale acompanhado de uma palavra
    do ramo do cliente na mesma manchete ou trecho. Devolve o termo, ou None."""
    if not ctx:
        return None
    nome = casa(ctx.get("nome") or [], topo)
    if not nome:
        return None
    junto = casa(ctx.get("com") or [], topo)
    return "%s (+%s)" % (nome, junto) if junto else None


def candidatos(lidos, clientes, termos_cfg, inicio, fim, publicadas, contexto=None, recentes=None):
    """Cruza os itens lidos com a carteira.

    lidos: [(feed, [itens])]. Feed com 'cliente' é sala de imprensa própria: todo
    item dentro da janela é daquele cliente. Sem 'cliente', cada item é cruzado
    com os termos de todos os clientes ativos — título e resumo primeiro, corpo
    por último (menção no corpo é mais fraca e vem marcada como tal).
    """
    ativos = {c["id"]: c for c in clientes if c.get("ativo") is not False}
    termos = {cid: termos_do(c, termos_cfg) for cid, c in ativos.items()}
    contexto = contexto or {}
    recentes = recentes or {}
    publicadas = {url_canonica(u) for u in publicadas}
    saida, vistos = [], set()
    repetidos = 0

    for feed, itens in lidos:
        for it in itens:
            quando = it.get("publicado")
            url = url_canonica(it.get("url"))
            if not url or quando is None or not (inicio <= quando <= fim):
                continue
            if url in publicadas:
                continue

            achados = []
            if feed.get("cliente"):
                if feed["cliente"] in ativos:
                    achados.append((feed["cliente"], "feed_proprio", None))
            else:
                topo = it["titulo"] + " " + it["resumo"]
                for cid, c in ativos.items():
                    excluir = c.get("excluir") or []
                    if excluir and casa(excluir, topo):
                        continue
                    t = casa(termos[cid], it["titulo"])
                    onde = "titulo"
                    if not t:
                        t, onde = casa(termos[cid], it["resumo"]), "resumo"
                    if not t:
                        ctx = casa_contexto(contexto.get(cid), topo)
                        if ctx:
                            nome_ctx = ctx.split(" (+")[0]
                            t = ctx
                            onde = "titulo" if casa([nome_ctx], it["titulo"]) else "resumo"
                    if not t:
                        t, onde = casa(termos[cid], it["corpo"]), "corpo"
                    if t:
                        achados.append((cid, onde, t))

            for cid, onde, termo in achados:
                if (cid, url) in vistos:
                    continue
                vistos.add((cid, url))
                # A mesma pauta já publicada por outro caminho: título idêntico
                # é a mesma matéria e sai daqui; parecido fica, mas marcado.
                parecido = None
                for data_ant, tit_ant in recentes.get(cid, []):
                    if mesmo_titulo(it["titulo"], tit_ant):
                        parecido = "identico"
                        break
                    if semelhanca(it["titulo"], tit_ant) >= LIMIAR_REPETICAO:
                        parecido = {"data": data_ant, "titulo": tit_ant}
                        break
                if parecido == "identico":
                    repetidos += 1
                    continue
                marca = feed.get("marca")
                nome_no_titulo = bool(casa(termos[cid] + ([marca] if marca else []), it["titulo"]))
                saida.append({
                    "cliente_id": cid,
                    "cliente": ativos[cid].get("nome", cid),
                    "titulo": it["titulo"],
                    "url": it.get("url", "").strip(),
                    "data": quando.astimezone(TZ).date().isoformat(),
                    "publicado_em": quando.astimezone(TZ).isoformat(timespec="minutes"),
                    "fonte": feed["nome"],
                    "trecho": (it["resumo"] or it["corpo"])[:TRECHO_MAX],
                    "tipo": "propria" if feed.get("cliente") else "setorial",
                    "onde": onde,
                    "termo": termo,
                    "nome_no_titulo": nome_no_titulo,
                    "pauta": classifica_pauta(it["titulo"], it["resumo"]),
                    **({"parecido_com": parecido} if parecido else {}),
                })

    peso = {"feed_proprio": 0, "titulo": 1, "resumo": 2, "corpo": 3}
    ordem_pauta = {"risco": 0, "gente": 1, "estrategia": 2, "geral": 3, "servico": 4}
    saida.sort(key=lambda c: (bool(c.get("parecido_com")), peso[c["onde"]],
                              ordem_pauta[c["pauta"]], c["cliente"], c["publicado_em"]))
    candidatos.repetidos = repetidos
    return saida


# ------------------------------------------------------------ rede

class Leitor:
    """Uma requisição por vez, identificada, respeitando robots.txt."""

    def __init__(self, agente):
        self.agente = agente
        self.robots = {}
        self.ultimo = {}

    def _pausa(self, host):
        falta = PAUSA_MESMO_SITE - (time.monotonic() - self.ultimo.get(host, 0))
        if falta > 0:
            time.sleep(falta)
        self.ultimo[host] = time.monotonic()

    def baixar(self, url):
        """(status_http, bytes). status 0 = falha de rede."""
        self._pausa(urlparse(url).netloc)
        req = urllib.request.Request(url, headers={
            "User-Agent": self.agente,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5",
        })
        try:
            with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception:
            pass
        # urllib falha em alguns certificados que o curl do sistema aceita
        r = subprocess.run(
            ["curl", "-s", "-L", "--max-time", str(TEMPO_LIMITE), "-A", self.agente,
             "-w", "\n%{http_code}", url],
            capture_output=True,
        )
        corpo, _, codigo = r.stdout.rpartition(b"\n")
        try:
            return int(codigo or 0), corpo
        except ValueError:
            return 0, b""

    def permite(self, url):
        """robots.txt, pela RFC 9309: 4xx libera tudo; 5xx ou rede fora do ar
        conta como proibição total, até conseguir ler de novo."""
        p = urlparse(url)
        base = "%s://%s" % (p.scheme, p.netloc)
        if base not in self.robots:
            status, corpo = self.baixar(base + "/robots.txt")
            rp = urllib.robotparser.RobotFileParser()
            if status == 200:
                rp.parse(corpo.decode("utf-8", "replace").splitlines())
                self.robots[base] = rp
            elif 400 <= status < 500:
                self.robots[base] = True
            else:
                self.robots[base] = False
        regra = self.robots[base]
        if regra is True or regra is False:
            return regra
        return regra.can_fetch(TOKEN_ROBOTS, url)


def pagina(url, n):
    if n == 1:
        return url
    return url + ("&" if "?" in url else "?") + "paged=%d" % n


def ler(feed, leitor, inicio, agora):
    """Lê um feed paginando até alcançar o início da janela.
    Devolve (itens, registro_de_saude)."""
    saude = {"status": "ok", "http": None, "itens_lidos": 0, "na_janela": 0,
             "paginas": 0, "alcance_horas": 0.0, "alcancou_janela": False}
    if feed.get("paginavel") is False:
        saude["parcial_aceito"] = True
    if not leitor.permite(feed["url"]):
        saude["status"] = "proibido_robots"
        return [], saude

    # O ponto de parada é o ÚLTIMO item de cada página, na ordem do feed — não o
    # mais antigo. Portais fixam matéria antiga no topo; usar o mínimo fazia a
    # leitura achar que já tinha chegado ao início da janela logo na página 1.
    itens, urls, fundo = [], set(), None
    for n in range(1, int(feed.get("paginas_max", 3)) + 1):
        status, corpo = leitor.baixar(pagina(feed["url"], n))
        if n == 1:
            saude["http"] = status
        if status != 200:
            if n == 1:
                saude["status"] = "rede" if status == 0 else "http_%d" % status
            break
        try:
            novos = ler_feed(corpo)
        except ValueError as e:
            if n == 1:
                saude["status"] = "formato"
                saude["erro"] = str(e)[:120]
            break
        novos = [i for i in novos if url_canonica(i["url"]) not in urls]
        if not novos:
            break  # feed que ignora ?paged= devolve a mesma página
        urls.update(url_canonica(i["url"]) for i in novos)
        itens.extend(novos)
        saude["paginas"] = n
        datas_pag = [i["publicado"] for i in novos if i["publicado"]]
        if datas_pag:
            fundo = datas_pag[-1]
            if fundo <= inicio:
                break

    saude["itens_lidos"] = len(itens)
    datas = [i["publicado"] for i in itens if i["publicado"]]
    if datas:
        saude["mais_novo_horas"] = round((agora - max(datas)).total_seconds() / 3600, 1)
    saude["na_janela"] = sum(1 for i in itens if i["publicado"] and inicio <= i["publicado"] <= agora)
    if fundo is not None:
        saude["alcance_horas"] = round((agora - fundo).total_seconds() / 3600, 1)
        saude["alcancou_janela"] = fundo <= inicio
    if saude["status"] == "ok" and not itens:
        saude["status"] = "vazio"
    return itens, saude


# ------------------------------------------------------------ saúde

def parado(reg):
    return reg.get("mais_novo_horas", 0) > PARADO_DIAS * 24


def alertas(historico, hoje):
    """Mudanças que merecem atenção, comparando hoje com os dias anteriores."""
    dias = sorted(d for d in historico if d < hoje)[-5:]
    avisos = []
    for nome, reg in sorted((historico.get(hoje) or {}).items()):
        antes = [historico[d][nome] for d in dias if nome in historico[d]]
        ok_antes = sum(1 for r in antes if r.get("status") == "ok")
        if reg["status"] != "ok" and ok_antes >= 3:
            avisos.append("%s passou a falhar hoje (%s) depois de %d de %d dias ok."
                          % (nome, reg["status"], ok_antes, len(antes)))
        if reg["status"] == "ok" and not reg.get("alcancou_janela") and not reg.get("parcial_aceito"):
            avisos.append("%s não alcançou o início da janela: cobre %.0f h. Suba paginas_max."
                          % (nome, reg.get("alcance_horas", 0)))
        if reg["status"] == "ok" and parado(reg) and not (antes and parado(antes[-1])):
            avisos.append("%s está parado: o item mais novo do feed tem %d dias. O editor não publica "
                          "mais por ele — troque o endereço ou tire o feed de fontes/feeds.json."
                          % (nome, reg["mais_novo_horas"] // 24))
        rendeu = [r.get("na_janela", 0) for r in antes if r.get("status") == "ok"]
        if reg["status"] == "ok" and reg.get("na_janela", 0) == 0 and len(rendeu) >= 3 and sum(rendeu) > 0:
            if all(historico[d].get(nome, {}).get("na_janela", 0) == 0 for d in dias[-2:]):
                avisos.append("%s está sem nenhum item na janela há 3 noites." % nome)
    return avisos


def registra_saude(caminho, hoje, registros):
    caminho = Path(caminho)
    historico = {}
    if caminho.exists():
        try:
            historico = json.loads(caminho.read_text(encoding="utf8"))
        except ValueError:
            historico = {}
    historico = {d: v for d, v in historico.items() if not d.startswith("_")}
    historico[hoje] = registros
    manter = sorted(historico)[-HISTORICO_DIAS:]
    historico = {d: historico[d] for d in manter}
    avisos = alertas(historico, hoje)
    saida = {"_sobre": "Saúde dos feeds da camada (e), uma entrada por noite. "
                       "Gerado por tools/feeds.py --saude; não edite à mão."}
    saida.update(historico)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf8")
    return avisos


# ------------------------------------------------------------ estado

def carrega_estado(caminho):
    txt = Path(caminho).read_text(encoding="utf8")
    if str(caminho).endswith(".json"):
        return json.loads(txt)
    m = re.search(r"/\*DADOS\*/(.*?)/\*FIM\*/", txt, re.S)
    if not m:
        raise SystemExit("FALHA: bloco /*DADOS*/ não encontrado em %s" % caminho)
    return json.loads(m.group(1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("estado")
    ap.add_argument("--horas", type=float, default=72)
    ap.add_argument("--ate")
    ap.add_argument("--saida")
    ap.add_argument("--saude")
    ap.add_argument("--registro", default=str(REGISTRO_PADRAO))
    a = ap.parse_args()

    estado = carrega_estado(a.estado)
    registro = json.loads(Path(a.registro).read_text(encoding="utf8"))
    termos_cfg = {k: v for k, v in (registro.get("termos") or {}).items() if not k.startswith("_")}
    contexto = {k: v for k, v in (registro.get("contexto") or {}).items() if not k.startswith("_")}

    fim = datetime.fromisoformat(a.ate) if a.ate else datetime.now(TZ)
    if fim.tzinfo is None:
        fim = fim.replace(tzinfo=TZ)
    inicio = fim - timedelta(hours=a.horas)
    hoje = fim.astimezone(TZ).date().isoformat()

    # Notícia já publicada não volta. A edição de hoje, se existir, não conta:
    # ela vai ser substituída.
    publicadas = {url_canonica(i.get("url")) for e in estado.get("edicoes") or []
                  if e.get("data", "") < hoje for i in e.get("itens") or []}
    limite = (fim.astimezone(TZ).date() - timedelta(days=DIAS_REPETICAO)).isoformat()
    recentes = {}
    for e in estado.get("edicoes") or []:
        if limite <= e.get("data", "") < hoje:
            for i in e.get("itens") or []:
                recentes.setdefault(i.get("cliente_id"), []).append((e["data"], i.get("titulo") or ""))

    leitor = Leitor(registro.get("agente") or "PautaThutor/1.0")
    lidos, saude = [], {}
    for feed in registro["feeds"]:
        itens, reg = ler(feed, leitor, inicio, fim)
        saude[feed["nome"]] = reg
        if itens:
            lidos.append((feed, itens))

    cands = candidatos(lidos, estado.get("clientes") or [], termos_cfg, inicio, fim, publicadas,
                       contexto, recentes)
    cobertos = sorted({urlparse(f["url"]).netloc.lower().removeprefix("www.")
                       for f in registro["feeds"] if saude[f["nome"]]["status"] == "ok"})

    print("camada (e) · feeds · janela %s → %s"
          % (inicio.astimezone(TZ).strftime("%d/%m %H:%M"), fim.astimezone(TZ).strftime("%d/%m %H:%M")))
    print()
    for f in registro["feeds"]:
        r = saude[f["nome"]]
        marca = "ok  " if r["status"] == "ok" else "!!  "
        print("%s%-26s %-16s %3d lidos · %3d na janela · %2d pág · alcance %5.0f h%s"
              % (marca, f["nome"], r["status"], r["itens_lidos"], r["na_janela"], r["paginas"],
                 r["alcance_horas"], "" if r["alcancou_janela"] or r["status"] != "ok"
                 else ("  (parcial, conhecido)" if r.get("parcial_aceito") else "  (curto)")))

    por_cliente = {}
    for c in cands:
        por_cliente.setdefault(c["cliente"], []).append(c)
    print()
    print("%d candidatos para %d clientes:" % (len(cands), len(por_cliente)))
    for nome in sorted(por_cliente, key=lambda n: -len(por_cliente[n])):
        lst = por_cliente[nome]
        tipos = sorted({c["onde"] for c in lst})
        pautas = ", ".join("%s %d" % (p, n) for p, n in
                           sorted(Counter(c["pauta"] for c in lst).items(), key=lambda x: -x[1]))
        print("  %-24s %3d  (%s · %s)" % (nome, len(lst), ", ".join(tipos), pautas))
    parecidos = sum(1 for c in cands if c.get("parecido_com"))
    if parecidos or getattr(candidatos, "repetidos", 0):
        print("  repetição: %d descartados por título idêntico a edição recente, %d marcados como parecidos"
              % (getattr(candidatos, "repetidos", 0), parecidos))

    avisos = registra_saude(a.saude, hoje, saude) if a.saude else []
    if avisos:
        print()
        print("ATENÇÃO — mudanças na saúde das fontes:")
        for av in avisos:
            print("  - " + av)

    if a.saida:
        Path(a.saida).write_text(json.dumps({
            "gerado_em": datetime.now(TZ).isoformat(timespec="seconds"),
            "janela": {"inicio": inicio.isoformat(timespec="minutes"), "fim": fim.isoformat(timespec="minutes")},
            "dominios_cobertos": cobertos,
            "alertas": avisos,
            "candidatos": cands,
        }, ensure_ascii=False, indent=1), encoding="utf8")
        print()
        print("candidatos gravados em " + a.saida)

    falhos = [n for n, r in saude.items() if r["status"] != "ok"]
    return 0 if len(falhos) < len(saude) else 1


if __name__ == "__main__":
    sys.exit(main())
