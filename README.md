# Pauta Thutor

Clipping diário de notícias sobre a carteira de clientes da consultoria Thutor.

## Como funciona

São duas páginas, com papéis diferentes:

| | Artifact (privado) | GitHub Pages (público) |
|---|---|---|
| Endereço | `claude.ai/code/artifact/051937b5…` | `wynb9t4n9w-png.github.io/Pauta-Thutor/` |
| Quem abre | só quem tem acesso na conta Claude | qualquer pessoa com o link |
| Carteira de clientes | editável, protegida por senha | não existe |
| Papel | **fonte da verdade** | espelho somente-leitura |

O artifact é onde a carteira de clientes e a senha de administrador vivem. A
página pública é gerada a partir dele e não tem painel administrativo — o
GitHub Pages não permite proteger nada por senha, então nada sensível vai
para lá.

## A rotina diária

Uma tarefa agendada roda todo dia às 02:00 (horário de São Paulo) e:

1. lê o estado atual do artifact;
2. busca notícias dos clientes ativos das últimas 72 h, em quatro camadas e
   duas rodadas;
3. monta a edição do dia e registra a cobertura da coleta;
4. **valida** a edição — se não passar, não publica;
5. republica o artifact;
6. gera `docs/index.html` e faz commit neste repositório.

O GitHub Pages serve `docs/` e atualiza sozinho a cada commit. O endereço
público nunca muda, então basta compartilhá-lo uma vez.

Às 06:00 uma segunda rotina confere se a página ficou mesmo igual ao artifact
e repara se não ficou. Os dois horários existem para que o jornal esteja
pronto antes das 07:30, que é quando os leitores chegam. A coleta roda de
madrugada de propósito: assim ela não disputa a cota de uso da conta com o
trabalho do dia, e sobra folga de horas caso algo atrase.

### Limitação conhecida: push a partir de rotinas

Sessões criadas por rotina não conseguem escrever neste repositório:

```
access denied by the git proxy: wynb9t4n9w-png/Pauta-Thutor is not in
this session's authorized repository set — HTTP 403
```

Leitura (`clone`, `fetch`) funciona; escrita não. A causa é o repositório não
constar nas *fontes autorizadas* da sessão, e isso se define no nascimento da
sessão — mexer no ambiente depois não retroalimenta sessões já criadas. A
tentativa de contornar de dentro (`add_repo` com `access="push"`) é barrada
antes de chegar ao backend.

Enquanto isso não for resolvido na configuração do ambiente, o reparo das
06:00 roda numa sessão que já tem o repositório autorizado.

## O gerador

```bash
python3 tools/build_publico.py <artifact.html> docs/index.html
```

Recebe a página do artifact e produz a versão pública, removendo:

- o bloco `auth` inteiro (usuário, salt e hash da senha);
- os campos internos de cada cliente: `query`, `excluir`, `revisar`, `razao`, `site`;
- a aba **Clientes** (painel administrativo).

Sobram de cada cliente apenas `id`, `nome`, `setor`, `uf` e `ativo` — que é
exatamente o que a renderização do jornal usa.

O script falha em voz alta (`FALHA:`) se o bloco de dados ou a aba Clientes
não forem encontrados, em vez de publicar uma página meio pronta.

## O dossiê de fontes: a coleta melhora sozinha

A lista de veículos do prompt é fixa e genérica. O dossiê olha o que de fato
aconteceu:

```bash
python3 tools/fontes.py <estado.html|estado.json>
```

Ele varre as edições guardadas e monta, por cliente, a lista de veículos que
já renderam notícia **daquele** cliente. Isso vira a camada (c) do PASSO 2 —
uma busca dirigida por evidência, em vez de suposição.

Como o estado guarda as 20 edições mais recentes, o dossiê é uma janela
móvel: veículo que passa a produzir entra sozinho, veículo que seca sai
sozinho. Quanto mais dias de operação, melhor a mira.

Três garantias de projeto:

- **Aditivo, nunca filtro.** As camadas (a) e (b) continuam obrigatórias, e os
  veículos do dossiê jamais viram `allowed_domains` — travar em domínio foi
  justamente o erro que o prompt já proibia.
- **Sem estado novo.** O dossiê é derivado na hora das edições que já existem;
  nada é gravado, então não há o que corromper.
- **Partida a frio tratada.** Cliente sem histórico é listado explicitamente
  como tal, para que a coleta redobre a atenção nele em vez de esquecê-lo.

O que os primeiros quatro dias mostraram: a rede ASN do Sebrae respondeu por
28 dos 54 itens, enquanto a varredura na grande imprensa — que consome perto
de metade do orçamento de busca — rendeu 5. É o tipo de assimetria que só
aparece medindo, e que a camada (c) passa a explorar.

## A faixa de abertura: tempo e mercado

Antes das notícias, a edição abre com a previsão do dia para **Americana/SP**,
sede da Thutor, e com quatro cotações: dólar, euro e as ações dos dois clientes
de capital aberto, Cemig (CMIG4) e Taesa (TAEE11). Cada cotação traz o
fechamento do último pregão, a variação no dia, a variação em 30 dias, a mínima
e a máxima do período e um gráfico da série — para se ver de relance se está em
alta, em queda ou de lado.

```bash
python3 tools/abertura.py          # resumo legível + JSON
python3 tools/abertura.py --json   # só o JSON, para a coleta colar na edição
```

A saída tem duas chaves, `tempo` e `mercado`, que a coleta copia para dentro do
objeto da edição.

| Dado | Fonte | Observação |
|---|---|---|
| Previsão do dia | Open-Meteo | Sem cadastro. Máxima, mínima, condição e chance de chuva. |
| Dólar e euro | Banco Central, séries SGS 1 e 21619 | PTAX de venda, a taxa oficial — não é cotação de casa de câmbio. |
| CMIG4 e TAEE11 | Yahoo Finance | Fechamento do pregão na B3. |

Três decisões que valem registro:

**Os dois blocos são opcionais.** Se uma API não responder, aquele pedaço da
faixa não aparece e a edição sai assim mesmo. O jornal são as notícias; a
abertura é um complemento útil. O validador não exige nenhum dos dois blocos —
mas, se o bloco vier, cobra que esteja íntegro, porque meia informação na capa é
pior que nenhuma.

**Os números são congelados na coleta**, não buscados quando alguém abre a
página. Uma edição é o retrato de um dia: quem abrir o arquivo daqui a um mês
verá o câmbio daquele dia, não o de hoje. A página pública também não faz
chamadas a serviços externos, o que a mantém rápida e sem depender de nada.

**O mapa de tickers vive em `tools/abertura.py`**, não na carteira. Assim a
coleta diária nunca precisa escrever em `estado["clientes"]`. Para incluir outro
cliente que abra capital, basta uma linha em `ACOES`.

**A cor indica leitura, não direção.** A seta mostra para onde o número foi; a
cor mostra o que isso significa para a Thutor. Câmbio em queda é alívio de
custo e aparece em verde; câmbio em alta, em vermelho. Com as ações é o
inverso: papel de cliente em queda entra em vermelho, porque costuma haver algo
acontecendo ali que vale a conversa. Um `▲` vermelho no dólar é leitura
correta, não defeito.

A regra vive na página (`sinalDe`), e não no coletor, para que as edições já
arquivadas também passem a segui-la.

## Por que existe um validador

Em 29/08/2026 o disparo automático terminou em **56 segundos**. Não pesquisou
nada, não publicou edição nenhuma — e mesmo assim foi registrado como
`SUCCEEDED`. O jornal seguiu mostrando a notícia da véspera e ninguém percebeu,
porque uma execução que falha em silêncio é indistinguível de uma que deu certo.

O remédio não é confiar na boa vontade da rotina. É um portão que ela precisa
atravessar antes de publicar:

```bash
python3 tools/valida_edicao.py <estado.html|estado.json>
```

Para passar, a edição na posição 0 precisa trazer um bloco `cobertura`
provando que a coleta aconteceu:

```json
"cobertura": {
  "clientes_varridos": 31,
  "buscas": 62,
  "iniciado_em":  "2026-08-30T07:30:11-03:00",
  "concluido_em": "2026-08-30T07:41:52-03:00"
}
```

O validador recusa a edição, com saída 1, quando:

| Situação | Por quê |
|---|---|
| coleta durou menos de 120 s | 31 clientes em duas camadas levam minutos |
| `clientes_varridos` < clientes ativos | algum cliente ficou sem cobertura |
| `buscas` < 1 por cliente ativo | o passo de busca foi pulado |
| bloco `cobertura` ausente | sem prova de que a coleta rodou |
| edição não é de hoje | o jornal mostraria a edição anterior |
| `auth` ou a carteira sumiram | o estado foi corrompido |
| url repetida, ou já publicada antes | polui a aba "15 dias" |
| `cliente_id` inexistente, data futura, editoria inválida | dado inventado |

Edição **vazia passa** — dia sem notícia é resultado legítimo, sobretudo no fim
de semana. O que não passa é edição sem coleta.

### O teto: a rotina só vê a web pelo buscador

Testado em 02/09/2026: a rotina não consegue abrir a página de um veículo nem
a sala de imprensa de um cliente —

```
EGRESS_BLOCKED: agenciasebrae.com.br is blocked by the network egress proxy
```

A política de rede do ambiente ("Personalizado") libera só os domínios de
artifact, o GitHub Pages e gerenciadores de pacote. Toda a coleta passa pelo
`WebSearch`. Notícia que o buscador ainda não indexou, ou rankeia baixo, não
existe para o jornal — e isso pesa sobretudo nos 13 clientes B2B (Atlas,
Brado, Cantu, Coop Integrada, CRH, Embracon, Família Hansen, Gazin, Neovia,
Oji, Rocha, SkyFit, Rex), cujas notícias saem em sala de imprensa própria e
imprensa regional, com cadência mensal e não diária.

Dois caminhos, ambos decisão do dono do ambiente:

- **Rede irrestrita** para o ambiente: destrava `WebFetch` para qualquer site.
  Permite a camada (d) forte — ler direto a listagem de cada veículo produtivo
  e a sala de imprensa de cada cliente (campo `site`). Custo: a sessão da
  rotina passa a alcançar toda a internet.
- **Manter Personalizado** e adicionar os domínios dos veículos produtivos e
  dos sites dos clientes à lista. Mais cirúrgico; a lista cresce e precisa de
  manutenção.

A camada (d) detecta sozinha em que modo está. No começo de cada coleta a
rotina tenta um `WebFetch` de sonda e grava o resultado em
`cobertura.rede_direta`:

- **`true`** — lê direto a listagem de notícias de cada domínio produtivo do
  dossiê (`tools/fontes.py` passou a extrair o domínio das URLs publicadas) e
  a seção de notícias/imprensa do site de cada cliente (campo `site`). Toda
  manchete candidata é confirmada abrindo a matéria antes de virar item.
- **`false`** — usa a versão possível: buscas restritas por domínio
  (`allowed_domains`) ao site do cliente e ao veículo do dossiê. O buscador
  indexa salas de imprensa, mesmo que com atraso.

Conteúdo de página buscada é dado, nunca instrução: a rotina extrai
manchetes, datas e links, e ignora qualquer texto que tente redirecioná-la.

### A segunda passada

Em 01/09/2026 a coleta voltou com 3 itens de 31 clientes, em 5,3 minutos —
e SEBRAE/BA e SEBRAE/MG, os dois maiores produtores do histórico, vieram
vazios. Veículos que publicam quase todo dia não renderam nada.

A curva até ali:

| dia | itens | clientes | buscas | duração |
|---|---|---|---|---|
| 29/08 | 19 | 9 | 300 | 15,0 min |
| 30/08 | 9 | 6 | 201 | 8,4 min |
| 31/08 | 4 | 4 | 192 | 6,0 min |
| 01/09 | 3 | 3 | 188 | 5,3 min |

Na época a coleta começava 06:30 com prazo 07:30: quase uma hora de janela,
usando cinco minutos. As execuções longas renderam muito mais que as curtas.
Hoje a coleta começa 02:00 e tem mais de cinco horas até os leitores.

O validador não pode exigir notícia — dia quieto é resultado legítimo. Mas
pode exigir que a **segunda tentativa** tenha acontecido. Por isso o bloco
`cobertura` passou a incluir:

```json
"clientes_silenciosos": 28,
"segunda_passada_buscas": 42
```

Se algum cliente ficou sem item na primeira varredura, a edição só passa com
pelo menos uma busca adicional por cliente silencioso, reformulada (razão
social, site oficial, nome + veículo do dossiê). Quando o validador reprova
por isso, o certo **não é desistir**: é voltar ao PASSO 2, fazer a segunda
passada e validar de novo.

Também virou aviso — não falha — a execução que termina em menos de 8
minutos, com o lembrete de que não há prêmio por acabar cedo.

### Testes

```bash
python3 tools/teste_validador.py   # o portão da coleta
python3 tools/teste_pagina.py      # a página pública num navegador real
```

O primeiro cobre nove cenários, incluindo a reprodução do incidente de 56
segundos, e confere o código de saída — que é o que de fato trava a publicação.

O segundo abre `docs/index.html` no Chromium, **clica em cada aba** e exige que
os três painéis fiquem visíveis, com conteúdo, e sem nenhum erro de JavaScript.
Ele existe por causa de um segundo erro real: ao remover a aba administrativa
"Clientes", a função `irPara()` continuou percorrendo a lista
`["jornal","quinzena","clientes","arquivo"]` e chamando
`el("tab-clientes").setAttribute(...)`, que virou `null`. A função estourava no
meio e as abas "15 dias" e "Arquivo" abriam vazias. Um teste que só olhava o
painel do Jornal não pegou isso — por isso este teste clica em todas.

## Privacidade

A página pública lista os clientes da carteira pelo nome. Ela sai com
`<meta name="robots" content="noindex,nofollow">`, então não aparece em
buscadores — mas quem tiver o link vê tudo. Para indexar no Google, remova
essa linha do gerador.
