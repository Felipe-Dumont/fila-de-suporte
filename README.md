# Fila de Suporte

App web em Python + SQLite para organizar duas filas de trabalho:
**Suporte** (o que travou e precisa ser resolvido agora) e **Demandas** (pedidos extras,
puxados conforme sobra tempo).

Sem framework, sem `pip install`, sem build. Só a biblioteca padrão do Python.
O núcleo e o servidor ficam em `app.py`, as telas ficam em `views/` e os dados em
`data.sqlite`.

---

## 1. Rodar em outra máquina

Requisito único: **Python 3.9 ou superior** (`zoneinfo` é usado quando existe; sem ele
o app cai num offset fixo de -03:00 e continua funcionando).

```bash
git clone <url-do-repositorio>
cd fila-de-suporte
python3 app.py                  # http://localhost:8000
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
| `argv[1]`            | `8000`    | Porta HTTP |
| `FILA_HOST`          | `0.0.0.0` | Interface de escuta. `0.0.0.0` expõe na rede local |

O banco `data.sqlite` é criado/migrado automaticamente no start (`init_db()`), ao lado
do `app.py`. **Este repositório já traz um `data.sqlite` com os dados reais** — ver
seção 6 antes de mexer nele.

Windows: use `py app.py`. macOS/Linux: `python3 app.py`.

---

## 2. Regras do projeto (leia antes de alterar qualquer coisa)

Estas são decisões deliberadas, não acidentes. Se for mudar alguma, mude com intenção
e atualize este README junto.

### Arquitetura

1. **Views por tela.** O núcleo e o servidor vivem em `app.py`. Cada tela pai fica em
   sua pasta dentro de `views/`; elementos reutilizados ficam em `views/comum/` e a
   implementação compartilhada das filas fica em `views/filas/`.
2. **Só biblioteca padrão.** Zero dependências externas. Nada de Flask, Django, Jinja,
   requests, pandas. Servidor é `http.server.ThreadingHTTPServer`; banco é `sqlite3`;
   HTML é montado com f-strings; os gráficos são **SVG gerado à mão** (`svg_colunas`,
   `svg_barras_h`). Se a solução exigir `pip install`, ela está errada para este projeto.
3. **Sem JavaScript.** A interface é HTML + CSS puros, com `<form>` e `<details>`.
   Não introduza JS nem front-end build.
4. **Padrão PRG.** Todo POST responde `303` redirecionando para um GET — nunca renderize
   HTML direto na resposta de um POST de ação (exceção: erro de validação em `/abrir`,
   que devolve `400` com o formulário preenchido).
5. **Código e comentários em português.** Nomes de funções, variáveis, rotas e textos de
   UI em pt-BR. Comentários explicam **o porquê**, não o quê.

### Segurança (escopo assumido)

6. Uso interno em rede local/confiável. **Não há autenticação** nas telas da equipe —
   isso é uma escolha consciente do escopo, não uma pendência.
7. O que é obrigatório manter: **SQL sempre parametrizado** (`?`, nunca f-string com valor
   do usuário) e **toda saída escapada** com o helper `e()` (`html.escape(..., quote=True)`).
   Não regrida nesses dois pontos.
8. Páginas públicas (`/abrir`, `/avaliar`) são acessíveis sem login e usam **token opaco**
   (`secrets.token_urlsafe(9)`) — nunca exponha o `id` numérico em link público.

### Regras de negócio

9. **A fila é por ordem de chegada** (`ORDER BY criado_em ASC, id ASC`). Prioridade
   (`baixa`/`normal`/`alta`) é **apenas marcador visual — não fura a fila**.
10. Ciclo de vida: `na_fila` → `em_atendimento` → `concluido`, e dá para reabrir
    (volta para `na_fila` e limpa `concluido_em`).
11. As duas filas moram na **mesma tabela**, separadas pela coluna `fila`
    (`suporte` | `demandas`). Os rótulos de cada uma vêm do dicionário `FILAS` —
    para mudar texto de UI de uma fila, edite `FILAS`, não o HTML espalhado.
12. `previsao` (data de entrega, `YYYY-MM-DD`) só existe em **demandas**. Em suporte a
    previsão é *calculada*, nunca digitada.
13. Quem abre pelo `/abrir` **não escolhe prioridade nem responsável** — isso é da equipe.
    A abertura pública sempre entra como `prioridade = 'normal'`.
14. **Avaliação nunca é obrigatória.** Item concluído sem nota é normal em toda a
    aplicação; nada pode quebrar por `nota IS NULL`.
15. **Anotação nasce privada** (`publica = 0`). Só vira visível ao solicitante por ação
    explícita na fila.
16. **Canonização de texto livre**: `dev` e `categoria` passam por `canonizar()`, que
    reaproveita a grafia já cadastrada quando o valor só difere em caixa/acento — senão
    "Contratos", "contratos" e "Contrato " virariam três categorias e os filtros rachariam.
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

O `app.py` concentra configuração, banco, regras, escrita, estilos e servidor:

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
| `views/filas/` | renderização compartilhada pelas duas filas |
| `views/comum/` | componentes e cascas compartilhadas |

**Para adicionar uma ação nova**: crie o `elif action == "..."` em `handle_action()`
(linha ~712) e o `<form method="post">` correspondente no render, incluindo
`campos_ocultos(f, fila)` para não perder fila e filtros no redirect.

### Rotas

| Método | Rota | Função |
|---|---|---|
| GET  | `/`            | Fila de suporte (aceita `?q=&status=&prio=&resp=&cat=`) |
| GET  | `/demandas`    | Fila de demandas (mesmos filtros) |
| GET  | `/alertas`     | Itens parados nas duas filas |
| GET  | `/painel`      | Métricas e gráficos (`?dias=7\|30\|90\|0`) |
| GET  | `/abrir`       | **Público** — formulário de abertura; `?ok=<token>` = recibo |
| GET  | `/avaliar?t=`  | **Público** — avaliação do atendimento concluído |
| POST | `/abrir`       | Cria via solicitante → `303` para o recibo |
| POST | `/avaliar`     | Grava nota → `303` de volta para a página pública |
| POST | qualquer outra | `handle_action()` → `303` para a fila (ou para `/alertas` se o form mandar `voltar=/alertas`) |

Ações aceitas em `handle_action()` (campo `action` do form):
`criar`, `editar`, `atribuir`, `anotar`, `nota_visivel`, `apagar_nota`,
`atender`, `concluir`, `reabrir`, `excluir`.

---

## 4. Modelo de dados

### `solicitacoes`

| Coluna | Tipo | Observação |
|---|---|---|
| `id`           | INTEGER PK AUTOINCREMENT | |
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

Índice: `idx_sol_token` (UNIQUE em `token`).

### `anotacoes`

| Coluna | Tipo | Observação |
|---|---|---|
| `id`             | INTEGER PK AUTOINCREMENT | |
| `solicitacao_id` | INTEGER NOT NULL | sem FK declarada; a exclusão é feita em código |
| `texto`          | TEXT NOT NULL | |
| `criado_em`      | TEXT NOT NULL DEFAULT `datetime('now')` | UTC |
| `publica`        | INTEGER NOT NULL DEFAULT `0` | `1` = visível ao solicitante |

Índice: `idx_anotacoes_sol` (em `solicitacao_id`).

### Como fazer migração de schema

`init_db()` roda a cada boot e é **idempotente**: `CREATE TABLE IF NOT EXISTS`,
`CREATE INDEX IF NOT EXISTS` e, para colunas novas, checagem via
`PRAGMA table_info(...)` antes do `ALTER TABLE ... ADD COLUMN`.

Para adicionar uma coluna, basta acrescentar a tupla `(nome, ddl)` na lista `novas`
dentro de `init_db()` (linha ~168). Nunca escreva migração destrutiva nem que dependa
de rodar uma única vez.

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

> Quando o projeto sair para hospedagem multiusuário, o banco deixa de ser versionado
> (entra no `.gitignore`) e vira MySQL/Postgres. Ver seção 6.

---

## 6. Caminho para hospedagem (MySQL / Vercel) — ainda não feito

Planejado, **não implementado**. Quem for fazer precisa saber que o desenho atual
assume SQLite local e um único processo:

1. `get_db()` (linha ~140) é o único ponto que abre conexão — é ali que entra o driver
   novo. Mas os `?` de placeholder mudam para `%s` no MySQL, e há ~40 chamadas `execute()`
   espalhadas: a troca não é de uma linha só.
2. `datetime('now')` (SQLite) vira `UTC_TIMESTAMP()` (MySQL). Aparece em `criado_em`,
   `concluido_em` e `nota_em`.
3. A função `norm()` é registrada em Python via `conn.create_function` — não existe no
   MySQL. A busca sem acento precisaria de collation `utf8mb4_0900_ai_ci` ou de uma
   coluna normalizada persistida.
4. `PRAGMA journal_mode` e `PRAGMA table_info` são específicos do SQLite; as migrações de
   `init_db()` teriam que virar `INFORMATION_SCHEMA.COLUMNS` ou um versionamento de schema
   de verdade (tabela `schema_version` + scripts numerados).
5. **Vercel não roda `ThreadingHTTPServer` com estado.** É serverless: cada request é um
   processo efêmero. Portar exige adaptar o `Handler` para função serverless (ou trocar
   por um host que rode processo longo — Railway, Render, Fly.io, VPS). Nesse cenário,
   a falta de autenticação (regra 6) deixa de ser aceitável e vira requisito.
6. **Migração dos dados**: exportar as duas tabelas do SQLite e importar no destino,
   preservando `id` e `token` (os links públicos já entregues dependem do `token`).

---

## 7. Contexto para IAs que forem trabalhar neste repositório

- Leia a seção 2 inteira antes de propor mudanças. As restrições (views separadas, zero
  dependências, sem JS) são o projeto, não obstáculos a contornar.
- Não há testes automatizados, nem linter, nem CI. Verificação é manual: rode
  `python3 app.py`, abra as telas afetadas e confira. Antes disso,
  `python3 -m py_compile app.py views/*/*.py` pega erro de sintaxe barato.
- Não crie `requirements.txt`, `Dockerfile`, `package.json` ou estrutura de pacote sem
  pedido explícito.
- Ao editar, siga o estilo do projeto: pt-BR, comentários curtos explicando o porquê,
  helpers pequenos, HTML montado por função `render_*`.
- Se precisar mexer no `data.sqlite`, leia a seção 5 primeiro — ele carrega dados reais.
