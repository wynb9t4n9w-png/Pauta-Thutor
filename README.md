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

Uma tarefa agendada roda todo dia às 06:30 (horário de São Paulo) e:

1. lê o estado atual do artifact;
2. busca notícias dos clientes ativos das últimas 24–48 h;
3. monta a edição do dia e registra a cobertura da coleta;
4. **valida** a edição — se não passar, não publica;
5. republica o artifact;
6. gera `docs/index.html` e faz commit neste repositório.

O GitHub Pages serve `docs/` e atualiza sozinho a cada commit. O endereço
público nunca muda, então basta compartilhá-lo uma vez.

Às 07:15 uma segunda rotina confere se a página ficou mesmo igual ao artifact
e repara se não ficou. Os dois horários existem para que o jornal esteja
pronto antes das 07:30, que é quando os leitores chegam.

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
07:15 roda numa sessão que já tem o repositório autorizado.

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
