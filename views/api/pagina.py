"""Página navegável de documentação da API privada."""

import html
import json


def _json_exemplo(valor: object) -> str:
    conteudo = json.dumps(valor, ensure_ascii=False, indent=2)
    return html.escape(conteudo)


def render_documentacao_api(token_configurado: bool) -> str:
    estado_classe = "ok" if token_configurado else "pendente"
    estado_texto = "API configurada" if token_configurado else "Token ainda não configurado"

    requisicao_criar = {
        "usuario": {
            "id": 123,
            "nome": "Maria da Silva",
            "email": "maria@locarmais.com.br",
        },
        "avaliacao": {
            "pendente": False,
            "nota": None,
        },
        "andamento": [
            {
                "texto": "A correção foi aplicada e está pronta para validação.",
                "criado_em": "2026-08-05 20:10:00",
                "criado_em_formatado": "05/08 17:10",
            }
        ],
        "categoria": "suporte",
        "assunto": "Não consigo emitir o boleto",
        "descricao": "Ao confirmar a emissão, a tela retorna uma mensagem de erro.",
    }
    chamado = {
        "id": 42,
        "assunto": "Não consigo emitir o boleto",
        "descricao": "Ao confirmar a emissão, a tela retorna uma mensagem de erro.",
        "categoria": "suporte",
        "prioridade": "normal",
        "status": "na_fila",
        "responsavel": "",
        "previsao": None,
        "criado_em": "2026-08-05 19:22:46",
        "criado_em_formatado": "05/08 16:22",
        "concluido_em": None,
        "concluido_em_formatado": None,
        "usuario": {
            "id": 123,
            "nome": "Maria da Silva",
            "email": "maria@locarmais.com.br",
        },
    }

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>SolicitaMais · Documentação da API</title>
    <link rel="icon" type="image/png" href="/imagens/logo-icone-solicitamais-favicon.png">
    <style>
        :root {{
            --roxo-950:#2b1238; --roxo-900:#3c1354; --roxo-800:#54206d;
            --roxo-700:#6f2c91; --roxo-600:#8738ad; --roxo-100:#f0e5f4;
            --rosa:#e72b87; --papel:#f7f6f8; --superficie:#fff;
            --texto:#211827; --suave:#706777; --linha:#e6dfe9;
            --verde:#16805b; --verde-bg:#e2f4ed; --ambar:#9a6200;
            --ambar-bg:#fff2d2; --vermelho:#b52c32; --vermelho-bg:#fbe5e6;
            --azul:#246bb2; --azul-bg:#e3f0fc;
        }}
        * {{ box-sizing:border-box; }}
        html {{ scroll-behavior:smooth; }}
        body {{ margin:0; background:var(--papel); color:var(--texto); font:15px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
        a {{ color:inherit; }}
        .layout {{ min-height:100vh; display:grid; grid-template-columns:280px minmax(0,1fr); }}
        aside {{ position:sticky; top:0; height:100vh; overflow:auto; background:var(--roxo-950); color:#fff; padding:28px 22px; }}
        .marca {{ display:flex; align-items:center; gap:12px; text-decoration:none; margin-bottom:30px; }}
        .marca img {{ width:42px; height:42px; object-fit:contain; border-radius:10px; background:#fff; padding:4px; }}
        .marca b {{ display:block; font-size:16px; }}
        .marca small {{ color:#cdbdd5; }}
        .nav-titulo {{ color:#9f8bab; font-size:10px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; margin:22px 10px 8px; }}
        nav {{ display:flex; flex-direction:column; gap:4px; }}
        nav a {{ color:#e5dce9; text-decoration:none; padding:9px 10px; border-radius:8px; font-size:13px; }}
        nav a:hover {{ background:rgba(255,255,255,.09); color:#fff; }}
        main {{ width:100%; max-width:1160px; padding:54px 54px 90px; }}
        .hero {{ background:linear-gradient(135deg,var(--roxo-900),var(--roxo-700)); color:#fff; border-radius:20px; padding:38px; box-shadow:0 18px 50px rgba(60,19,84,.18); }}
        .hero-topo {{ display:flex; justify-content:space-between; align-items:flex-start; gap:24px; flex-wrap:wrap; }}
        .kicker {{ color:#f0b7d4; font-size:12px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }}
        h1 {{ font-size:38px; line-height:1.15; letter-spacing:-.035em; margin:9px 0 12px; }}
        .hero p {{ color:#e7dcec; max-width:690px; margin:0; font-size:16px; }}
        .estado {{ display:inline-flex; align-items:center; gap:8px; border:1px solid rgba(255,255,255,.22); border-radius:999px; padding:7px 12px; font-size:12px; white-space:nowrap; }}
        .estado::before {{ content:""; width:8px; height:8px; border-radius:50%; background:#f0b429; }}
        .estado.ok::before {{ background:#41d69b; }}
        .base-url {{ margin-top:28px; background:rgba(18,5,27,.34); border:1px solid rgba(255,255,255,.14); border-radius:11px; padding:12px 15px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
        section {{ scroll-margin-top:28px; margin-top:48px; }}
        h2 {{ color:var(--roxo-900); font-size:25px; letter-spacing:-.02em; margin:0 0 8px; }}
        .intro {{ color:var(--suave); margin:0 0 20px; max-width:780px; }}
        .card {{ background:var(--superficie); border:1px solid var(--linha); border-radius:15px; padding:24px; box-shadow:0 8px 24px rgba(54,33,62,.045); }}
        .auth-grid,.resumo-grid,.status-grid {{ display:grid; gap:14px; }}
        .auth-grid {{ grid-template-columns:1fr 1fr; }}
        .resumo-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
        .status-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
        .mini {{ border:1px solid var(--linha); border-radius:12px; padding:16px; background:#fdfcfd; }}
        .mini b {{ display:block; color:var(--roxo-900); margin-bottom:3px; }}
        .mini span {{ color:var(--suave); font-size:13px; }}
        code,pre {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
        code.inline {{ color:var(--roxo-700); background:var(--roxo-100); border-radius:5px; padding:2px 6px; }}
        pre {{ overflow:auto; margin:12px 0 0; padding:17px; color:#eee8f1; background:#211527; border-radius:11px; font-size:12.5px; line-height:1.65; }}
        .endpoint {{ background:var(--superficie); border:1px solid var(--linha); border-radius:16px; overflow:hidden; margin-top:18px; box-shadow:0 8px 24px rgba(54,33,62,.045); }}
        .endpoint summary {{ cursor:pointer; list-style:none; display:flex; align-items:center; gap:12px; padding:19px 22px; }}
        .endpoint summary::-webkit-details-marker {{ display:none; }}
        .endpoint[open] summary {{ border-bottom:1px solid var(--linha); }}
        .metodo {{ min-width:64px; text-align:center; border-radius:7px; padding:5px 8px; font-size:11px; font-weight:900; letter-spacing:.06em; }}
        .get {{ color:var(--azul); background:var(--azul-bg); }}
        .post {{ color:var(--verde); background:var(--verde-bg); }}
        .caminho {{ color:var(--roxo-950); font-size:15px; font-weight:750; }}
        .descricao-rota {{ color:var(--suave); margin-left:auto; font-size:13px; text-align:right; }}
        .endpoint-corpo {{ padding:24px; }}
        .endpoint-corpo h3 {{ color:var(--roxo-900); font-size:14px; margin:25px 0 8px; }}
        .endpoint-corpo h3:first-child {{ margin-top:0; }}
        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th,td {{ padding:11px 12px; border-bottom:1px solid var(--linha); text-align:left; vertical-align:top; }}
        th {{ color:var(--suave); font-size:11px; letter-spacing:.06em; text-transform:uppercase; }}
        tr:last-child td {{ border-bottom:0; }}
        .obrigatorio {{ color:var(--vermelho); font-size:10px; font-weight:800; text-transform:uppercase; }}
        .codigo {{ display:inline-block; min-width:42px; border-radius:6px; padding:3px 7px; font-weight:800; text-align:center; }}
        .s2 {{ color:var(--verde); background:var(--verde-bg); }}
        .s4 {{ color:var(--ambar); background:var(--ambar-bg); }}
        .s5 {{ color:var(--vermelho); background:var(--vermelho-bg); }}
        .nota {{ border-left:4px solid var(--rosa); background:#fff5fa; border-radius:0 10px 10px 0; padding:13px 15px; color:#654758; margin-top:14px; }}
        .rodape {{ color:var(--suave); border-top:1px solid var(--linha); margin-top:55px; padding-top:22px; font-size:12px; }}
        @media (max-width:900px) {{
            .layout {{ display:block; }} aside {{ position:static; height:auto; }} aside nav {{ display:none; }}
            .nav-titulo {{ display:none; }} main {{ padding:28px 18px 60px; }}
            .auth-grid,.resumo-grid,.status-grid {{ grid-template-columns:1fr; }}
            h1 {{ font-size:30px; }} .descricao-rota {{ display:none; }}
        }}
    </style>
</head>
<body>
<div class="layout">
    <aside>
        <a class="marca" href="/api">
            <img src="/imagens/logo-icone-solicitamais-favicon.png" alt="SolicitaMais">
            <span><b>SolicitaMais API</b><small>Referência v1</small></span>
        </a>
        <div class="nav-titulo">Começar</div>
        <nav>
            <a href="#visao-geral">Visão geral</a>
            <a href="#autenticacao">Autenticação</a>
            <a href="#fluxo-acesso">Controle de acesso</a>
        </nav>
        <div class="nav-titulo">Endpoints</div>
        <nav>
            <a href="#listar">GET · Listar chamados</a>
            <a href="#criar">POST · Criar chamado</a>
            <a href="#openapi">GET · OpenAPI JSON</a>
        </nav>
        <div class="nav-titulo">Referência</div>
        <nav>
            <a href="#status">Códigos de resposta</a>
            <a href="#modelo">Modelo de chamado</a>
            <a href="/">Voltar ao SolicitaMais</a>
        </nav>
    </aside>

    <main>
        <header class="hero" id="visao-geral">
            <div class="hero-topo">
                <div>
                    <div class="kicker">API privada · versão 1</div>
                    <h1>Integração de chamados</h1>
                    <p>Crie solicitações no SolicitaMais e acompanhe o atendimento dentro do LocarMais, preservando a identidade e o acesso de cada usuário.</p>
                </div>
                <span class="estado {estado_classe}">{estado_texto}</span>
            </div>
            <div class="base-url">Base URL: http://host.docker.internal:8001</div>
        </header>

        <section id="autenticacao">
            <h2>Autenticação</h2>
            <p class="intro">Todos os endpoints de dados exigem um Bearer Token compartilhado somente pelos backends. A documentação e a especificação OpenAPI são públicas.</p>
            <div class="card auth-grid">
                <div>
                    <strong>Cabeçalho obrigatório</strong>
                    <pre>Authorization: Bearer &lt;SOLICITAMAIS_API_TOKEN&gt;
Accept: application/json</pre>
                </div>
                <div>
                    <strong>Configuração no LocarMais</strong>
                    <pre>SOLICITAMAIS_API_URL=http://host.docker.internal:8001
SOLICITAMAIS_API_TOKEN=mesmo-token-do-python</pre>
                </div>
            </div>
            <div class="nota">Nunca envie o token ao navegador e nunca permita que o frontend informe livremente o ID do usuário autenticado.</div>
        </section>

        <section id="fluxo-acesso">
            <h2>Controle de acesso</h2>
            <p class="intro">A autorização por usuário acontece no backend do LocarMais antes da chamada à API.</p>
            <div class="resumo-grid">
                <div class="mini"><b>Usuário comum</b><span>O Laravel envia seu ID e nome. A API inclui os chamados vinculados ao ID e os manuais sem origem abertos com o mesmo nome.</span></div>
                <div class="mini"><b>Super Admin</b><span>O Laravel omite os filtros e recebe todos os chamados, inclusive os criados diretamente no SolicitaMais.</span></div>
                <div class="mini"><b>Avaliação obrigatória</b><span>Um chamado concluído sem nota bloqueia uma nova abertura daquele usuário até o envio da avaliação.</span></div>
            </div>
        </section>

        <section id="listar">
            <h2>Endpoints</h2>
            <p class="intro">Clique em cada operação para consultar parâmetros, exemplos e respostas.</p>
            <details class="endpoint" open>
                <summary><span class="metodo get">GET</span><span class="caminho">/api/chamados</span><span class="descricao-rota">Lista chamados do LocarMais</span></summary>
                <div class="endpoint-corpo">
                    <h3>Parâmetros de consulta</h3>
                    <table>
                        <thead><tr><th>Nome</th><th>Tipo</th><th>Obrigatório</th><th>Descrição</th></tr></thead>
                        <tbody>
                            <tr><td><code>usuario_id</code></td><td>integer</td><td>Não</td><td>Filtra pelo ID estável do usuário autenticado.</td></tr>
                            <tr><td><code>usuario_nome</code></td><td>string</td><td>Não</td><td>Inclui chamados sem ID de origem quando o nome do solicitante corresponder. Quando os filtros são omitidos, retorna todos os chamados.</td></tr>
                        </tbody>
                    </table>
                    <h3>Exemplo</h3>
                    <pre>curl "http://localhost:8001/api/chamados?usuario_id=123&amp;usuario_nome=Sistema" \
  -H "Authorization: Bearer $SOLICITAMAIS_API_TOKEN" \
  -H "Accept: application/json"</pre>
                    <h3>Resposta 200</h3>
                    <pre>{_json_exemplo({"dados": [chamado]})}</pre>
                </div>
            </details>

            <details class="endpoint" id="criar" open>
                <summary><span class="metodo post">POST</span><span class="caminho">/api/chamados</span><span class="descricao-rota">Cria um chamado identificado</span></summary>
                <div class="endpoint-corpo">
                    <h3>Corpo JSON</h3>
                    <table>
                        <thead><tr><th>Campo</th><th>Tipo</th><th>Regra</th><th>Descrição</th></tr></thead>
                        <tbody>
                            <tr><td><code>usuario.id</code></td><td>integer</td><td><span class="obrigatorio">Obrigatório</span></td><td>ID positivo do usuário autenticado no LocarMais.</td></tr>
                            <tr><td><code>usuario.nome</code></td><td>string</td><td><span class="obrigatorio">Obrigatório</span></td><td>De 1 a 255 caracteres.</td></tr>
                            <tr><td><code>usuario.email</code></td><td>string</td><td>Opcional</td><td>Até 255 caracteres.</td></tr>
                            <tr><td><code>categoria</code></td><td>string</td><td><span class="obrigatorio">Obrigatório</span></td><td><code>suporte</code> ou <code>demandas</code>.</td></tr>
                            <tr><td><code>assunto</code></td><td>string</td><td><span class="obrigatorio">Obrigatório</span></td><td>De 1 a 160 caracteres.</td></tr>
                            <tr><td><code>descricao</code></td><td>string</td><td>Opcional</td><td>Até 2.000 caracteres.</td></tr>
                        </tbody>
                    </table>
                    <h3>Requisição</h3>
                    <pre>{_json_exemplo(requisicao_criar)}</pre>
                    <h3>Resposta 201</h3>
                    <pre>{_json_exemplo({"dados": chamado})}</pre>
                    <h3>Resposta 422</h3>
                    <pre>{_json_exemplo({"mensagem": "Revise os dados enviados.", "erros": {"assunto": "O assunto deve ter entre 1 e 160 caracteres."}})}</pre>
                </div>
            </details>

            <details class="endpoint" id="avaliar" open>
                <summary><span class="metodo post">POST</span><span class="caminho">/api/avaliacoes</span><span class="descricao-rota">Avalia um chamado concluído</span></summary>
                <div class="endpoint-corpo">
                    <p>O backend da LocarMais envia a identidade autenticada. A avaliação só é aceita quando o chamado pertence ao usuário e já está concluído.</p>
                    <h3>JSON enviado</h3>
                    <pre>{_json_exemplo({"usuario": requisicao_criar["usuario"], "chamado_id": 42, "nota": 5, "observacao": "Atendimento resolvido."})}</pre>
                    <h3>Resposta 200</h3>
                    <pre>{_json_exemplo({"dados": chamado, "mensagem": "Avaliação registrada. Obrigado!"})}</pre>
                </div>
            </details>
        </section>

        <section id="openapi">
            <h2>Especificação OpenAPI</h2>
            <p class="intro">A descrição estruturada pode ser importada no Insomnia, Postman ou em uma interface Swagger compatível.</p>
            <div class="card"><a href="/api/openapi.json"><strong>Abrir /api/openapi.json</strong></a></div>
        </section>

        <section id="status">
            <h2>Códigos de resposta</h2>
            <div class="card status-grid">
                <div class="mini"><span class="codigo s2">200</span><b>Consulta concluída</b><span>Lista retornada com sucesso.</span></div>
                <div class="mini"><span class="codigo s2">201</span><b>Chamado criado</b><span>Novo registro persistido.</span></div>
                <div class="mini"><span class="codigo s4">400</span><b>JSON inválido</b><span>Corpo ausente ou malformado.</span></div>
                <div class="mini"><span class="codigo s4">401</span><b>Não autorizado</b><span>Bearer Token ausente ou incorreto.</span></div>
                <div class="mini"><span class="codigo s4">413</span><b>Payload excedido</b><span>Corpo maior que 64 KiB.</span></div>
                <div class="mini"><span class="codigo s4">422</span><b>Validação</b><span>Parâmetro ou campo inválido.</span></div>
                <div class="mini"><span class="codigo s5">503</span><b>Não configurada</b><span>Token ausente no ambiente Python.</span></div>
            </div>
        </section>

        <section id="modelo">
            <h2>Modelo de chamado</h2>
            <p class="intro">O mesmo formato é usado na criação e nos itens da listagem.</p>
            <div class="card"><pre>{_json_exemplo(chamado)}</pre></div>
        </section>

        <footer class="rodape">SolicitaMais API v1 · Integração privada com o LocarMais · Datas armazenadas em UTC e formatadas em America/Sao_Paulo.</footer>
    </main>
</div>
</body>
</html>"""
