# -*- coding: utf-8 -*-
"""Comparação de textos e endereços, usada pelo validador e pela camada (e).

Existe em um lugar só para que os dois comparem do mesmo jeito. Nasceu do
estudo de qualidade de 30/09/2026, que achou a mesma matéria publicada duas
vezes em dias seguidos por dois caminhos diferentes:

  - o Sesc DF serve o mesmo endereço ora com o acento codificado
    (corrida-do-comerci%C3%A1rio), ora com o acento literal (comerciário) —
    para uma comparação de texto cru, são duas URLs;
  - o release sai na agência do cliente e é republicado por um jornal regional
    com o título idêntico e outro domínio.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

# Palavras que não distinguem uma pauta de outra. "sebrae" está aqui de
# propósito: aparece em quase todo título da ASN e faria tudo parecer igual.
_VAZIAS = set("""
para com como mais pelo pela pelos pelas sobre entre desde apos este esta esse essa
isso aquele aquela numa num dos das nos nas que por sua seu suas seus uma uns umas
ser tem teem esta estao foi sao ate ano anos novo nova novos novas sebrae
""".split())

# Parâmetros de rastreamento que não mudam o conteúdo da página.
_RASTREIO = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$|amp$)")

# A partir daqui, duas manchetes do mesmo cliente contam a mesma pauta.
# Calibrado no histórico de 11 a 30/09/2026: pega "Prêmio Sebrae Mulher de
# Negócios" repetido, a eleição da diretora da CCEE por dois veículos e o JCP
# da Cemig em dois dias; deixa de fora o mesmo programa em cidades diferentes.
LIMIAR_REPETICAO = 0.5


def normaliza(txt):
    """Minúsculas e sem acento, para 'Sebrae Pará' casar com 'SEBRAE PARA'."""
    txt = unicodedata.normalize("NFD", (txt or "").lower())
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")


def url_canonica(u):
    """Forma única de um endereço, para comparar publicação com publicação.

    Decodifica %xx, ignora esquema, 'www.', maiúsculas no domínio, barra final,
    fragmento e parâmetros de rastreamento.
    """
    u = unquote((u or "").strip())
    if not u:
        return ""
    p = urlsplit(u if "://" in u else "https://" + u)
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    consulta = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                          if not _RASTREIO.match(k.lower())])
    caminho = p.path.rstrip("/")
    return urlunsplit(("", host, caminho, consulta, "")).lstrip("/")


def titulo_canonico(t):
    return re.sub(r"[^a-z0-9]+", " ", normaliza(t)).strip()


def palavras(t):
    return {w for w in titulo_canonico(t).split() if len(w) >= 4 and w not in _VAZIAS}


def semelhanca(a, b):
    """Nota de 0 a 1: média entre a semelhança das sequências de letras e a
    proporção de palavras relevantes em comum. As duas juntas erram menos que
    cada uma sozinha: a primeira se engana com fórmulas de título ('Sebrae leva
    X a Y'); a segunda, com títulos curtos."""
    ta, tb = titulo_canonico(a), titulo_canonico(b)
    if not ta or not tb:
        return 0.0
    seq = SequenceMatcher(None, ta, tb).ratio()
    pa, pb = palavras(a), palavras(b)
    jac = len(pa & pb) / len(pa | pb) if (pa | pb) else 0.0
    return round((seq + jac) / 2, 3)


def mesmo_titulo(a, b):
    return bool(titulo_canonico(a)) and titulo_canonico(a) == titulo_canonico(b)
