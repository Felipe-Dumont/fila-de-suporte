# SolicitaMais

App web em Python com SQLite local e PostgreSQL/Supabase em produção para organizar duas filas de trabalho:
**Suporte** (o que travou e precisa ser resolvido agora) e **Demandas** (pedidos extras,
puxados conforme sobra tempo).

Sem framework e sem build. O núcleo e o servidor ficam em `app.py`, as telas ficam em
`views/`; o `data.sqlite` é usado quando `DATABASE_URL` não está configurada.

---

## 1. Rodar em outra máquina

Use **Python 3.12**. Somente o acesso ao PostgreSQL exige a dependência declarada em
`requirements.txt`; o modo SQLite continua usando apenas a biblioteca padrão.

```bash
git clone <url-do-repositorio>
cd fila-de-suporte
cp .env.example .env
# edite o .env e use o mesmo SOLICITAMAIS_API_TOKEN do LocarMais
python3 app.py                  # SQLite local, se DATABASE_URL estiver vazia
```

Para rodar localmente conectado ao Supabase:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py        # http://localhost:8001 com o .env.example
```

O terminal imprime dois endereços: o `localhost` (só esta máquina) e o da rede local
(o que as outras pessoas no mesmo Wi-Fi devem abrir). `Ctrl+C` encerra.

Opções:

```bash
python3 app.py 8080                       # outra porta (1º argumento posicional)
FILA_HOST=127.0.0.1 python3 app.py        # restringe só a esta máquina
```

| Variável / argumento | Padrão    | O que faz |
|----------------------|-----------|-----------|
| `argv[1]`            | —         | Quando informado, substitui `FILA_PORT` |
| `FILA_HOST`          | `0.0.0.0` | Interface de escuta. `0.0.0.0` expõe na rede local |
| `FILA_PORT`          | `8000`    | Porta HTTP quando não há argumento posicional |
| `SOLICITAMAIS_API_TOKEN` | vazio | Token Bearer compartilhado exclusivamente com o backend do LocarMais |
| `DATABASE_URL` | vazio | URL PostgreSQL; vazia mantém o uso do `data.sqlite` |
| `SOLICITAMAIS_ADMIN_USUARIO` | vazio | Usuário HTTP Basic das telas internas |
| `SOLICITAMAIS_ADMIN_SENHA` | vazio | Senha HTTP Basic das telas internas |

O arquivo `.env` é carregado automaticamente. Variáveis definidas diretamente no
processo têm precedência, permitindo sobrescrever a configuração sem editar o arquivo.
O `.env` local está no `.gitignore`; somente o `.env.example`, sem segredos, é versionado.

O schema é criado/migrado automaticamente no start (`init_db()`). **Este repositório
traz um `data.sqlite` com dados reais** — ver a seção 5 antes de mexer nele.

Windows: use `py app.py`. macOS/Linux: `python3 app.py`.

---

## 2. Regras do projeto (leia antes de alterar qualquer coisa)

Estas são decisões deliberadas, não acidentes. Se for mudar alguma, mude com intenção
e atualize este README junto.

### Arquitetura

1. **Módulos por responsabilidade.** O núcleo e o servidor vivem em `app.py`. Cada tela
   pai fica em sua pasta dentro de `views/`; elementos reutilizados ficam em
   `views/comum/`; e o despacho, autenticação e contrato HTTP da API ficam em `rotas/`.
2. **Sem framework.** Servidor é `http.server.ThreadingHTTPServer`; HTML é montado com
   f-strings; os gráficos são **SVG gerado à mão** (`svg_colunas`, `svg_barras_h`). A
   única dependência externa permitida é `psycopg`, usada quando `DATABASE_URL` aponta
   para PostgreSQL. Não introduza outras dependências sem uma decisão explícita.
3. **JavaScript progressivo e sem build.** A interface usa HTML + CSS e formulários por
   padrão. JavaScript puro melhora as telas internas com `fetch`, além de cuidar do
   Kanban e da cópia de links. Sem JavaScript, os formulários continuam funcionando
   pelo fluxo HTML + PRG. Não introduza dependências ou build.
4. **Padrão PRG nas telas.** Todo POST de formulário responde `303` redirecionando para
   um GET — nunca renderize HTML direto na resposta de uma ação (exceções: erro de
   validação em `/abrir`, que devolve `400`, a API JSON privada e a movimentação
   assíncrona do Kanban).
5. **Código e comentários em português.** Nomes de funções, variáveis, rotas e textos de
   UI em pt-BR. Comentários explicam **o porquê**, não o quê.

### Segurança (escopo assumido)

6. Em rede local, as telas internas podem continuar sem autenticação. Em hospedagem
   pública, configure `SOLICITAMAIS_ADMIN_USUARIO` e `SOLICITAMAIS_ADMIN_SENHA`; isso
   protege as telas da equipe com HTTP Basic sem bloquear `/abrir` e `/avaliar`.
7. O que é obrigatório manter: **SQL sempre parametrizado** (`?`, nunca f-string com valor
   do usuário) e **toda saída escapada** com o helper `e()` (`html.escape(..., quote=True)`).
   Não regrida nesses dois pontos.
8. Páginas públicas (`/abrir`, `/avaliar`) são acessíveis sem login e usam **token opaco**
   (`secrets.token_urlsafe(9)`) — nunca exponha o `id` numérico em link público.
   A rota `/api/chamados` é privada e exige o Bearer token configurado em
   `SOLICITAMAIS_API_TOKEN`.

### Regras de negócio

9. **A fila é por ordem de chegada** (`ORDER BY criado_em ASC, id ASC`). Prioridade
   (`baixa`/`normal`/`alta`) é **apenas marcador visual — não fura a fila**.
10. Ciclo de vida: `na_fila` → `em_atendimento` → `concluido`, e dá para reabrir
    (volta para `na_fila` e limpa `concluido_em`). **Concluir exige responsável**:
    sem `dev` preenchido nada é gravado, tanto na ação `concluir` quanto ao mover
    um card para a coluna "Concluídos" do Kanban. Quando o chamado ainda não tem
    dono, o próprio botão Concluir abre o campo que cadastra quem atendeu.
11. As duas filas moram na **mesma tabela**, separadas pela coluna `fila`
    (`suporte` | `demandas`). Os rótulos de cada uma vêm do dicionário `FILAS` —
    para mudar texto de UI de uma fila, edite `FILAS`, não o HTML espalhado.
12. `previsao` (data de entrega, `YYYY-MM-DD`) só existe em **demandas**. Em suporte a
    previsão é *calculada*, nunca digitada.
13. Quem abre pelo `/abrir` **não escolhe prioridade nem responsável** — isso é da equipe.
    A abertura pública sempre entra como `prioridade = 'normal'`.
14. **Avaliação exigida na integração.** Usuários do LocarMais precisam avaliar o
    chamado concluído sem nota antes de abrir outro. Nas demais entradas, `nota IS NULL`
    continua sendo um estado válido.
15. **Anotação nasce privada** (`publica = 0`). Só vira visível ao solicitante por ação
    explícita na fila.
16. **Canonização de texto livre**: `dev` e `categoria` passam por `canonizar()`, que
    reaproveita a grafia já cadastrada quando o valor só difere em caixa/acento — senão
    "Contratos", "contratos" e "Contrato " virariam três categorias e os filtros rachariam.
    Nas telas internas, `solicitante`, `categoria` e o responsável pedido na conclusão são
    campos de **escolha ou cadastro** (`campo_combo()`): um `<select>` com o que já foi
    usado mais a opção "Cadastrar…", que libera o texto enviado em `<campo>_novo`. O
    servidor lê os dois com `valor_combo()`, que só formata o valor novo — a opção
    escolhida volta com a grafia exata do banco. A lista sai das próprias solicitações;
    não existe tabela de cadastros.
17. **Não prometa o que não dá para medir.** A estimativa de suporte exige ≥ 5 conclusões
    nos últimos 30 dias; a projeção do painel exige janela ≥ 7 dias e ≥ 3 conclusões.
    Sem isso, o valor sai vazio de propósito.
18. **Datas: UTC no banco, local na tela.** O banco grava `datetime('now')` (UTC, formato
    `YYYY-MM-DD HH:MM:SS`); a exibição converte para `America/Sao_Paulo` via os helpers
    `_parse_utc` / `quando` / `quando_previsto`. Nunca grave hora local no banco.

### Alertas

19. Suporte vira alerta quando fica **mais de `LIMITE_ESPERA_HORAS` (2h)** em `na_fila`
    sem ninguém iniciar.
20. Demanda vira alerta quando **chega o dia da `previsao` (ou passa)** e ela ainda está
    em `na_fila`.
21. Item **já iniciado nunca é alerta** — a régua é sobre coisa parada.

### Visual

22. A paleta dos gráficos (`COR_SUPORTE`, `COR_DEMANDAS`, `RAMPA_IDADE`) foi validada
    para contraste e daltonismo (CVD) contra o fundo branco dos cards. Trocar cor de
    gráfico no olho é regressão — revalide antes.
23. O CSS inteiro é a constante `CSS`, com as cores em custom properties no `:root`.
    Mexa nas variáveis, não em cada regra.

---

## 3. Mapa do código

O `app.py` concentra banco, regras, escrita, estilos e servidor, delegando telas e API:

| Faixa aprox. | Bloco | O que tem |
|---|---|---|
| 12–123   | Configuração | imports, `DB_PATH`, `PORT`, `HOST`, constantes de status/prioridade, dicionário `FILAS`, paleta, `EXPEDIENTE` |
| 129–212  | Banco | `get_db()`, `init_db()` (schema + migrações idempotentes), `normalizar()`, `novo_token()` |
| 218–396  | Helpers de exibição | `e()` (escape), datas/durações, `prazo()`, `estimativa_suporte()`, `canonizar()`, `carregar_notas()` |
| 396–571  | Gráficos SVG | `svg_colunas()`, `svg_barras_h()`, `tabela_viz()`, `legenda()` |
| 573–631  | Alertas | `espera_estourada()`, `prazo_vencido()`, `buscar_alertas()`, `render_banner()` |
| 637–710  | Filtros | `ler_filtros()`, `query_string()`, `campos_ocultos()`, `_condicoes()` |
| 712–852  | **Escritas** | `handle_action()` (todas as ações da equipe), `salvar_avaliacao()`, `abrir_solicitacao()` |
| 858–…    | CSS | constante `CSS` |
| final    | Views | configuração das dependências e imports de `views/` |
| final    | `Handler` | roteamento `do_GET` / `do_POST` |
| final    | Boot | `ip_local()`, `main()` |

As telas estão organizadas assim:

| Pasta | Responsabilidade |
|---|---|
| `views/suporte/` | tela pai da fila de suporte |
| `views/demandas/` | tela pai da fila de demandas |
| `views/alertas/` | itens que precisam de atenção |
| `views/painel/` | métricas e gráficos |
| `views/abrir/` | abertura pública e confirmação |
| `views/avaliar/` | acompanhamento e avaliação pública |
| `views/concluidos/` | histórico unificado de chamados concluídos |
| `views/filas/` | renderização compartilhada pelas duas filas |
| `views/comum/` | componentes e cascas compartilhadas |
| `views/api/` | site visual de documentação da API |
| `rotas/api.py` | endpoints, autenticação, validação e especificação OpenAPI |
| `views/kanban/` | quadro, filtros e interação de arrastar chamados |
| `rotas/kanban.py` | consulta e persistência das movimentações do Kanban |
| `configuracao/cores.py` | paleta e variáveis de cor do SolicitaMais |
| `configuracao/api.py` | token e limite de payload da integração privada |
| `configuracao/ambiente.py` | carregamento do `.env` com a biblioteca padrão |
| `configuracao/banco.py` | seleção SQLite/PostgreSQL e adaptação parametrizada do SQL |
| `configuracao/acesso.py` | autenticação HTTP Basic opcional das telas internas |
| `api/index.py` | entrada serverless da Vercel |
| `scripts/migrar_sqlite_para_postgres.py` | migração única e segura dos dados locais |

**Para adicionar uma ação nova**: crie o `elif action == "..."` em `handle_action()`
(linha ~712) e o `<form method="post">` correspondente no render, incluindo
`campos_ocultos(f, fila)` para não perder fila e filtros no redirect.

### Rotas

| Método | Rota | Função |
|---|---|---|
| GET  | `/`            | Fila de suporte (aceita `?q=&status=&prio=&resp=&cat=`) |
| GET  | `/demandas`    | Fila de demandas (mesmos filtros) |
| GET  | `/alertas`     | Itens parados nas duas filas |
| GET  | `/painel`      | Métricas (`?dias=7\|30\|90\|0`, `?data=AAAA-MM-DD`, `?pessoa=Nome`) |
| GET  | `/concluidos`  | Histórico concluído; aceita `?q=&fila=&resp=&cat=&prio=` |
| GET  | `/kanban` | Quadro; concluídos dos últimos 5 dias; aceita `?q=&fila=&resp=&cat=` |
| GET  | `/abrir`       | **Público** — formulário de abertura; `?ok=<token>` = recibo |
| GET  | `/avaliar?t=`  | **Público** — avaliação do atendimento concluído |
| GET  | `/api` | **Público** — documentação visual da API |
| GET  | `/api/documentacao` | Alias da documentação visual |
| GET  | `/api/openapi.json` | Especificação OpenAPI 3.1 para Postman, Insomnia ou Swagger |
| GET  | `/api/chamados` | **Privado** — aceita `?usuario_id=<id>&usuario_nome=<nome>` |
| POST | `/abrir`       | Cria via solicitante → `303` para o recibo |
| POST | `/avaliar`     | Grava nota → `303` de volta para a página pública |
| POST | `/api/chamados` | **Privado** — cria chamado identificado com o usuário do LocarMais |
| POST | `/api/avaliacoes` | **Privado** — avalia um chamado concluído do usuário autenticado |
| POST | `/kanban/mover` | Atualiza etapa, status e responsável ao mover um card |
| POST | qualquer outra | `handle_action()` → `303` para a fila (ou para `/alertas` se o form mandar `voltar=/alertas`) |

As duas chamadas da API exigem `Authorization: Bearer <token>`. O backend do LocarMais
envia a identidade do usuário autenticado; esse dado não é aceito diretamente do
navegador. Com ID e nome, o GET também inclui chamados manuais sem origem cujo
solicitante tenha o mesmo nome. Sem os filtros, retorna todos os chamados e deve ser
usado apenas pelo fluxo de Super Admin.

Cada chamado retorna a situação da avaliação e o andamento público, sem expor o token
do link externo. O POST de criação retorna `422` quando o mesmo usuário possui um
chamado concluído sem avaliação.

Ações aceitas em `handle_action()` (campo `action` do form):
`criar`, `editar`, `atribuir`, `anotar`, `nota_visivel`, `apagar_nota`,
`atender`, `concluir`, `reabrir`, `excluir`.

---

## 4. Modelo de dados

### `solicitacoes`

| Coluna | Tipo | Observação |
|---|---|---|
| `id`           | INTEGER PK AUTOINCREMENT / BIGSERIAL | SQLite / PostgreSQL |
| `solicitante`  | TEXT NOT NULL | obrigatório |
| `assunto`      | TEXT NOT NULL | obrigatório |
| `descricao`    | TEXT NOT NULL DEFAULT `''` | |
| `prioridade`   | TEXT NOT NULL DEFAULT `'normal'` | `baixa` \| `normal` \| `alta` — visual apenas |
| `status`       | TEXT NOT NULL DEFAULT `'na_fila'` | `na_fila` \| `em_atendimento` \| `concluido` |
| `criado_em`    | TEXT NOT NULL DEFAULT `datetime('now')` | UTC |
| `concluido_em` | TEXT | UTC; `NULL` enquanto não concluído |
| `fila`         | TEXT NOT NULL DEFAULT `'suporte'` | `suporte` \| `demandas` |
| `dev`          | TEXT NOT NULL DEFAULT `''` | responsável nas duas filas |
| `previsao`     | TEXT | `YYYY-MM-DD`; só em demandas |
| `categoria`    | TEXT NOT NULL DEFAULT `''` | |
| `token`        | TEXT | único; chave dos links públicos |
| `nota`         | INTEGER | 1–5; `NULL` = não avaliado |
| `nota_obs`     | TEXT NOT NULL DEFAULT `''` | máx. 1000 chars |
| `nota_em`      | TEXT | UTC |
| `origem_sistema` | TEXT NOT NULL DEFAULT `''` | `locarmais` nos chamados criados pela integração |
| `origem_usuario_id` | INTEGER | ID estável do usuário no LocarMais |
| `origem_usuario_nome` | TEXT NOT NULL DEFAULT `''` | nome registrado no momento da abertura |
| `origem_usuario_email` | TEXT NOT NULL DEFAULT `''` | e-mail registrado no momento da abertura |

Índices: `idx_sol_token` (UNIQUE em `token`) e `idx_sol_origem_usuario`
(em `origem_sistema`, `origem_usuario_id`).

### `anotacoes`

| Coluna | Tipo | Observação |
|---|---|---|
| `id`             | INTEGER PK AUTOINCREMENT / BIGSERIAL | SQLite / PostgreSQL |
| `solicitacao_id` | INTEGER NOT NULL / BIGINT NOT NULL | PostgreSQL usa FK com `ON DELETE CASCADE` |
| `texto`          | TEXT NOT NULL | |
| `criado_em`      | TEXT NOT NULL DEFAULT `datetime('now')` | UTC |
| `publica`        | INTEGER NOT NULL DEFAULT `0` | `1` = visível ao solicitante |

Índice: `idx_anotacoes_sol` (em `solicitacao_id`).

### Como fazer migração de schema

`init_db()` roda a cada boot e é **idempotente**. No SQLite usa
`PRAGMA table_info(...)`; no PostgreSQL usa `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

Para adicionar uma coluna, atualize as duas variantes dentro de `init_db()`: a lista
`novas` do SQLite e `colunas_solicitacoes` do PostgreSQL. Nunca escreva migração
destrutiva nem que dependa de rodar uma única vez.

---

## 5. Banco de dados versionado no Git

**O `data.sqlite` está commitado neste repositório de propósito**, para não perder os
dados atuais enquanto o projeto ainda roda em uma máquina só.

Consequências que quem for mexer precisa saber:

- É um **binário**: o Git não faz merge dele. Se duas pessoas alterarem dados e ambas
  commitarem, o conflito só se resolve escolhendo um arquivo inteiro (`git checkout --ours`
  / `--theirs`). Combine antes quem mexe.
- Os arquivos `data.sqlite-wal` e `data.sqlite-shm` estão no `.gitignore` — são estado
  transitório de uma execução em andamento.
- **Antes de commitar o banco, pare o app e force o checkpoint do WAL**, senão o commit
  pode sair sem as últimas escritas:

  ```bash
  python3 -c "import sqlite3; c=sqlite3.connect('data.sqlite'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
  git add data.sqlite && git commit -m "dados: snapshot da fila"
  ```

- **Backup:** copie o `data.sqlite`. **Zerar tudo:** apague `data.sqlite` (e os `-wal` /
  `-shm`, se existirem) — ele é recriado vazio no próximo boot.

O arquivo continua sendo a base local e a origem da migração inicial. Em produção, a
Vercel nunca grava nele: `DATABASE_URL` seleciona o PostgreSQL.

---

## 6. Hospedagem na Vercel com Supabase

O projeto já possui `api/index.py`, `vercel.json`, `.python-version` e
`requirements.txt`. Na Vercel:

1. Importe este repositório e mantenha **Framework Preset = Other**.
2. Cadastre `DATABASE_URL` usando a URL do **Transaction Pooler** do Supabase (porta
   `6543`), `SOLICITAMAIS_API_TOKEN`, `SOLICITAMAIS_ADMIN_USUARIO` e
   `SOLICITAMAIS_ADMIN_SENHA` nos ambientes desejados.
3. Faça o deploy. O primeiro cold start executa o schema idempotente.
4. Atualize a URL do SolicitaMais no `.env` do LocarMais para o domínio da Vercel.

Para migrar o conteúdo do SQLite uma única vez, com o PostgreSQL vazio:

```bash
.venv/bin/python scripts/migrar_sqlite_para_postgres.py
```

O script preserva IDs e tokens e cancela sem alterar nada caso encontre registros no
destino. Revise a autorização para enviar dados reais antes de executá-lo.

---

## 7. Contexto para IAs que forem trabalhar neste repositório

- Leia a seção 2 inteira antes de propor mudanças. As restrições (views separadas,
  dependência externa limitada ao driver PostgreSQL e JavaScript mínimo) são o projeto.
- Não há testes automatizados, nem linter, nem CI. Verificação é manual: rode
  `python3 app.py`, abra as telas afetadas e confira. Antes disso,
  `python3 -m py_compile app.py configuracao/*.py rotas/*.py views/*/*.py` pega erro de sintaxe barato.
- Não acrescente dependências ao `requirements.txt`, `Dockerfile`, `package.json` ou
  outra estrutura de implantação sem pedido explícito.
- Ao editar, siga o estilo do projeto: pt-BR, comentários curtos explicando o porquê,
  helpers pequenos, HTML montado por função `render_*`.
- Se precisar mexer no `data.sqlite`, leia a seção 5 primeiro — ele carrega dados reais.
