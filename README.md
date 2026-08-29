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

Uma tarefa agendada roda todo dia às 07:30 (horário de São Paulo) e:

1. lê o estado atual do artifact;
2. busca notícias dos clientes ativos das últimas 24–48 h;
3. monta a edição do dia e republica o artifact;
4. gera `docs/index.html` com o script abaixo e faz commit neste repositório.

O GitHub Pages serve `docs/` e atualiza sozinho a cada commit. O endereço
público nunca muda, então basta compartilhá-lo uma vez.

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

## Privacidade

A página pública lista os clientes da carteira pelo nome. Ela sai com
`<meta name="robots" content="noindex,nofollow">`, então não aparece em
buscadores — mas quem tiver o link vê tudo. Para indexar no Google, remova
essa linha do gerador.
