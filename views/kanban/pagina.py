"""Renderização do quadro Kanban de chamados."""

import html


ETAPAS = (
    ("pendente", "Pendentes sem atribuição", "Aguardando alguém assumir", "pendente"),
    ("atribuido", "Atribuídos", "Com responsável, ainda não iniciados", "atribuido"),
    ("andamento", "Em andamento", "Atendimento iniciado", "andamento"),
    ("concluido", "Concluídos", "Finalizados nos últimos 5 dias", "concluido"),
)


def _e(valor: object) -> str:
    return html.escape(str(valor or ""), quote=True)


def _etapa_chamado(chamado) -> str:
    if chamado["status"] == "concluido":
        return "concluido"
    if chamado["status"] == "em_atendimento":
        return "andamento"
    return "atribuido" if chamado["dev"] else "pendente"


def _opcoes(valores: list[str], selecionado: str, vazio: str) -> str:
    opcoes = [f'<option value="">{_e(vazio)}</option>']
    for valor in valores:
        marcado = " selected" if valor == selecionado else ""
        opcoes.append(f'<option value="{_e(valor)}"{marcado}>{_e(valor)}</option>')
    return "".join(opcoes)


def _card(chamado, etapa_atual: str, quando) -> str:
    descricao = (
        f'<p class="kanban-card-desc">{_e(chamado["descricao"])}</p>'
        if chamado["descricao"] else ""
    )
    categoria = (
        f'<span class="kanban-chip categoria">{_e(chamado["categoria"])}</span>'
        if chamado["categoria"] else ""
    )
    fila = "Demanda" if chamado["fila"] == "demandas" else "Suporte"
    responsavel = chamado["dev"] or "Sem responsável"
    opcoes_etapa = "".join(
        f'<option value="{chave}"{" selected" if chave == etapa_atual else ""}>{_e(titulo)}</option>'
        for chave, titulo, _, _ in ETAPAS
    )

    return f"""
    <article class="kanban-card" draggable="true" tabindex="0"
             data-id="{chamado['id']}" data-responsavel="{_e(chamado['dev'])}"
             data-etapa="{etapa_atual}">
        <div class="kanban-card-topo">
            <span class="kanban-id">#{chamado['id']}</span>
            <span class="kanban-chip fila {_e(chamado['fila'])}">{fila}</span>
        </div>
        <h3>{_e(chamado['assunto'])}</h3>
        {descricao}
        <div class="kanban-chips">{categoria}</div>
        <dl class="kanban-meta">
            <div><dt>Solicitante</dt><dd>{_e(chamado['solicitante'])}</dd></div>
            <div><dt>Responsável</dt><dd class="card-responsavel">{_e(responsavel)}</dd></div>
            <div><dt>Aberto</dt><dd>{_e(quando(chamado['criado_em']))}</dd></div>
        </dl>
        <div class="kanban-mover">
            <select class="mover-select" aria-label="Mover chamado #{chamado['id']}">
                {opcoes_etapa}
            </select>
            <button class="btn ghost mover-botao" type="button">Mover</button>
        </div>
    </article>"""


def render_kanban(
    chamados,
    filtros: dict,
    responsaveis: list[str],
    categorias: list[str],
    quando,
) -> str:
    grupos = {chave: [] for chave, _, _, _ in ETAPAS}
    for chamado in chamados:
        etapa = _etapa_chamado(chamado)
        grupos[etapa].append(_card(chamado, etapa, quando))

    colunas = ""
    for chave, titulo, subtitulo, classe in ETAPAS:
        cards = "".join(grupos[chave])
        vazio = '<div class="kanban-vazio">Arraste um chamado para cá</div>' if not cards else ""
        colunas += f"""
        <section class="kanban-coluna {classe}" data-destino="{chave}">
            <header class="kanban-coluna-topo">
                <div><h2>{titulo}</h2><p>{subtitulo}</p></div>
                <span class="kanban-contador">{len(grupos[chave])}</span>
            </header>
            <div class="kanban-cards">{cards}{vazio}</div>
        </section>"""

    filas = [
        ("", "Todas as filas"),
        ("suporte", "Suporte"),
        ("demandas", "Demandas"),
    ]
    opcoes_fila = "".join(
        f'<option value="{valor}"{" selected" if filtros["fila"] == valor else ""}>{rotulo}</option>'
        for valor, rotulo in filas
    )
    opcoes_responsavel = _opcoes(responsaveis, filtros["resp"], "Todos os responsáveis")
    opcoes_responsavel = opcoes_responsavel.replace(
        "</select>", ""
    )
    sem_responsavel = (
        '<option value="—" selected>Sem responsável</option>'
        if filtros["resp"] == "—"
        else '<option value="—">Sem responsável</option>'
    )
    opcoes_categoria = _opcoes(categorias, filtros["cat"], "Todas as categorias")
    datalist_responsaveis = "".join(
        f'<option value="{_e(responsavel)}">' for responsavel in responsaveis
    )

    return f"""
    <style>{ESTILOS_KANBAN}</style>
    <div class="kanban-shell" data-filtro-responsavel="{_e(filtros['resp'])}">
        <form class="kanban-filtros" method="get" action="/kanban">
            <div class="kanban-busca">
                <label for="kanban-q">Buscar</label>
                <input id="kanban-q" type="search" name="q" value="{_e(filtros['q'])}"
                       placeholder="Assunto, solicitante ou descrição">
            </div>
            <div>
                <label for="kanban-fila">Fila</label>
                <select id="kanban-fila" name="fila">{opcoes_fila}</select>
            </div>
            <div>
                <label for="kanban-resp">Responsável</label>
                <select id="kanban-resp" name="resp">{opcoes_responsavel}{sem_responsavel}</select>
            </div>
            <div>
                <label for="kanban-cat">Categoria</label>
                <select id="kanban-cat" name="cat">{opcoes_categoria}</select>
            </div>
            <div class="kanban-filtro-acoes">
                <button class="btn ghost" type="submit">Filtrar</button>
                <a class="btn ghost" href="/kanban">Limpar</a>
            </div>
        </form>

        <div class="kanban-legenda">
            <span><i class="pi-arraste">⋮⋮</i> Arraste os cards entre as colunas</span>
            <b>{len(chamados)} chamado{"s" if len(chamados) != 1 else ""}</b>
        </div>

        <div class="kanban-board">{colunas}</div>
    </div>

    <datalist id="kanban-responsaveis">{datalist_responsaveis}</datalist>
    <dialog id="responsavel-dialog" class="kanban-dialog">
        <form method="dialog">
            <div class="dialog-icone">👤</div>
            <h2>Quem ficará com este chamado?</h2>
            <p>Para mover para esta etapa, informe o responsável pelo atendimento.</p>
            <label for="novo-responsavel">Responsável</label>
            <input id="novo-responsavel" list="kanban-responsaveis" maxlength="80"
                   autocomplete="off" placeholder="Digite ou selecione um nome">
            <div class="dialog-acoes">
                <button class="btn ghost" value="cancelar">Cancelar</button>
                <button class="btn primary" value="confirmar">Confirmar</button>
            </div>
        </form>
    </dialog>
    <div id="kanban-toast" class="kanban-toast" role="status" aria-live="polite"></div>
    <script>{SCRIPT_KANBAN}</script>"""


ESTILOS_KANBAN = """
.kanban-shell { width:min(1480px,calc(100vw - 32px)); position:relative; left:50%; transform:translateX(-50%); }
.kanban-filtros { display:grid; grid-template-columns:minmax(240px,1.5fr) repeat(3,minmax(150px,1fr)) auto; gap:10px; align-items:end; padding:15px; margin-bottom:14px; background:var(--surface); border:1px solid var(--line); border-radius:12px; }
.kanban-filtros label { margin:0 0 5px; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
.kanban-filtros input,.kanban-filtros select { padding:8px 10px; }
.kanban-filtro-acoes { display:flex; gap:7px; padding-bottom:1px; }
.kanban-legenda { display:flex; justify-content:space-between; align-items:center; gap:12px; color:var(--muted); font-size:12px; margin:0 2px 10px; }
.kanban-legenda b { color:var(--ink); }
.pi-arraste { color:var(--signal); font-style:normal; letter-spacing:-3px; margin-right:5px; }
.kanban-board { display:grid; grid-template-columns:repeat(4,minmax(285px,1fr)); gap:12px; align-items:stretch; height:clamp(480px,calc(100vh - 240px),800px); overflow-x:auto; overflow-y:hidden; padding:1px 1px 12px; overscroll-behavior:contain; }
.kanban-coluna { display:flex; flex-direction:column; min-width:285px; min-height:0; background:var(--surface-muted); border:1px solid var(--line); border-radius:14px; overflow:hidden; }
.kanban-coluna-topo { display:flex; justify-content:space-between; align-items:flex-start; gap:10px; padding:15px; border-top:4px solid var(--warning); background:var(--surface); }
.kanban-coluna.atribuido .kanban-coluna-topo { border-top-color:var(--signal); }
.kanban-coluna.andamento .kanban-coluna-topo { border-top-color:var(--info); }
.kanban-coluna.concluido .kanban-coluna-topo { border-top-color:var(--success); }
.kanban-coluna-topo h2 { margin:0; color:var(--ink); font-size:14px; }
.kanban-coluna-topo p { margin:2px 0 0; color:var(--muted); font-size:11px; }
.kanban-contador { min-width:27px; padding:3px 7px; border-radius:999px; color:var(--muted); background:var(--surface-muted); font-size:11px; font-weight:700; text-align:center; }
.kanban-cards { min-height:0; flex:1; display:flex; flex-direction:column; gap:9px; padding:10px; overflow-y:auto; overscroll-behavior:contain; scrollbar-gutter:stable; transition:background .15s; }
.kanban-cards::-webkit-scrollbar { width:9px; }
.kanban-cards::-webkit-scrollbar-track { background:var(--surface-muted); }
.kanban-cards::-webkit-scrollbar-thumb { background:var(--line-strong); border:2px solid var(--surface-muted); border-radius:999px; }
.kanban-cards::-webkit-scrollbar-thumb:hover { background:var(--muted); }
.kanban-coluna.arrastando-sobre .kanban-cards { background:var(--primary-soft,var(--surface-soft)); outline:2px dashed var(--signal); outline-offset:-6px; }
.kanban-card { cursor:grab; padding:14px; background:var(--surface); border:1px solid var(--line); border-radius:11px; box-shadow:0 2px 7px rgba(45,33,51,.05); transition:transform .15s,box-shadow .15s,opacity .15s; }
.kanban-card:hover { transform:translateY(-1px); box-shadow:0 7px 18px rgba(45,33,51,.09); }
.kanban-card:active { cursor:grabbing; }
.kanban-card.sendo-arrastado { opacity:.42; transform:rotate(1deg); }
.kanban-card.movendo { opacity:.55; pointer-events:none; }
.kanban-card-topo { display:flex; justify-content:space-between; align-items:center; gap:8px; }
.kanban-id { color:var(--muted); font:700 11px ui-monospace,SFMono-Regular,Menlo,monospace; }
.kanban-chip { display:inline-flex; width:max-content; padding:2px 7px; border-radius:999px; font-size:10px; font-weight:700; }
.kanban-chip.fila { color:var(--signal-active); background:var(--dev-bg); }
.kanban-chip.fila.demandas { color:var(--accent-ink); background:var(--accent-bg); }
.kanban-chip.categoria { color:var(--muted); background:var(--surface-muted); }
.kanban-card h3 { margin:10px 0 5px; color:var(--ink); font-size:14px; line-height:1.35; }
.kanban-card-desc { display:-webkit-box; overflow:hidden; -webkit-box-orient:vertical; -webkit-line-clamp:2; margin:0 0 9px; color:var(--text-secondary); font-size:11.5px; }
.kanban-chips { display:flex; flex-wrap:wrap; gap:5px; }
.kanban-meta { display:flex; flex-direction:column; gap:5px; margin:11px 0 0; padding-top:9px; border-top:1px solid var(--line); }
.kanban-meta div { display:grid; grid-template-columns:76px minmax(0,1fr); gap:6px; font-size:11px; }
.kanban-meta dt { color:var(--muted); }
.kanban-meta dd { overflow:hidden; margin:0; color:var(--ink); font-weight:600; text-overflow:ellipsis; white-space:nowrap; }
.kanban-mover { display:flex; gap:6px; margin-top:11px; }
.kanban-mover select { flex:1; min-width:0; padding:6px 7px; font-size:11px; }
.kanban-mover .btn { padding:6px 8px; font-size:11px; }
.kanban-vazio { display:flex; align-items:center; justify-content:center; min-height:170px; padding:18px; color:var(--muted); border:1px dashed var(--line-strong); border-radius:10px; font-size:11px; text-align:center; }
.kanban-dialog { width:min(430px,calc(100vw - 30px)); padding:0; border:0; border-radius:15px; box-shadow:0 25px 70px rgba(43,18,56,.28); }
.kanban-dialog::backdrop { background:rgba(27,16,33,.52); backdrop-filter:blur(2px); }
.kanban-dialog form { padding:25px; }
.kanban-dialog .dialog-icone { width:42px; height:42px; display:grid; place-items:center; background:var(--dev-bg); border-radius:11px; }
.kanban-dialog h2 { margin:14px 0 4px; font-size:18px; }
.kanban-dialog p { margin:0 0 16px; color:var(--muted); font-size:13px; }
.kanban-dialog label { margin-top:0; }
.dialog-acoes { display:flex; justify-content:flex-end; gap:8px; margin-top:18px; }
.dialog-acoes .btn.primary { width:auto; margin:0; }
.kanban-toast { position:fixed; right:22px; bottom:22px; z-index:100; max-width:390px; padding:12px 15px; color:var(--surface); background:var(--ink); border-radius:10px; box-shadow:0 12px 35px rgba(0,0,0,.22); opacity:0; pointer-events:none; transform:translateY(8px); transition:.2s; }
.kanban-toast.visivel { opacity:1; transform:translateY(0); }
.kanban-toast.erro { background:var(--danger); color:var(--danger-ink); }
@media (max-width:1050px) { .kanban-filtros { grid-template-columns:repeat(2,minmax(0,1fr)); } .kanban-filtro-acoes { align-self:end; } }
@media (max-width:620px) { .kanban-shell { width:calc(100vw - 22px); } .kanban-filtros { grid-template-columns:1fr; } .kanban-board { grid-template-columns:repeat(4,86vw); height:clamp(440px,calc(100vh - 210px),720px); } .kanban-filtro-acoes .btn { flex:1; justify-content:center; } }
"""


SCRIPT_KANBAN = """
(() => {
    const colunas = [...document.querySelectorAll('.kanban-coluna')];
    const dialog = document.querySelector('#responsavel-dialog');
    const campoResponsavel = document.querySelector('#novo-responsavel');
    const toast = document.querySelector('#kanban-toast');
    const filtroResponsavel = document.querySelector('.kanban-shell').dataset.filtroResponsavel;
    let cardArrastado = null;
    let timerToast = null;

    function avisar(mensagem, erro = false) {
        clearTimeout(timerToast);
        toast.textContent = mensagem;
        toast.className = `kanban-toast visivel${erro ? ' erro' : ''}`;
        timerToast = setTimeout(() => toast.className = 'kanban-toast', 3500);
    }

    function pedirResponsavel() {
        campoResponsavel.value = '';
        dialog.showModal();
        setTimeout(() => campoResponsavel.focus(), 50);
        return new Promise((resolve) => {
            dialog.addEventListener('close', () => {
                resolve(dialog.returnValue === 'confirmar' ? campoResponsavel.value.trim() : '');
            }, { once: true });
        });
    }

    function atualizarColunas() {
        for (const coluna of colunas) {
            const cards = coluna.querySelector('.kanban-cards');
            const total = cards.querySelectorAll('.kanban-card').length;
            coluna.querySelector('.kanban-contador').textContent = total;
            const vazio = cards.querySelector('.kanban-vazio');
            if (!total && !vazio) {
                cards.insertAdjacentHTML('beforeend', '<div class="kanban-vazio">Arraste um chamado para cá</div>');
            } else if (total && vazio) {
                vazio.remove();
            }
        }
    }

    async function mover(card, destino) {
        if (!card || destino === card.dataset.etapa) return;

        let responsavel = card.dataset.responsavel.trim();
        if ((destino === 'atribuido' || destino === 'andamento') && !responsavel) {
            responsavel = await pedirResponsavel();
            if (!responsavel) return;
        }

        card.classList.add('movendo');
        try {
            const resposta = await fetch('/kanban/mover', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify({
                    id: Number(card.dataset.id),
                    destino,
                    responsavel,
                }),
            });
            const corpo = await resposta.json().catch(() => ({}));
            if (!resposta.ok) throw new Error(corpo.mensagem || 'Não foi possível mover o chamado.');

            const novaColuna = document.querySelector(`.kanban-coluna[data-destino="${destino}"] .kanban-cards`);
            card.dataset.etapa = destino;
            card.dataset.responsavel = corpo.dados.responsavel || '';
            card.querySelector('.card-responsavel').textContent = corpo.dados.responsavel || 'Sem responsável';
            card.querySelector('.mover-select').value = destino;
            const responsavelAtual = corpo.dados.responsavel || '';
            const permaneceNoFiltro = !filtroResponsavel
                || (filtroResponsavel === '—' ? !responsavelAtual : filtroResponsavel === responsavelAtual);
            if (permaneceNoFiltro) novaColuna.appendChild(card);
            else card.remove();
            atualizarColunas();
            avisar('Chamado atualizado com sucesso.');
        } catch (erro) {
            avisar(erro.message, true);
        } finally {
            card.classList.remove('movendo');
        }
    }

    for (const card of document.querySelectorAll('.kanban-card')) {
        card.addEventListener('dragstart', (evento) => {
            if (evento.target.closest('select,button')) {
                evento.preventDefault();
                return;
            }
            cardArrastado = card;
            card.classList.add('sendo-arrastado');
            evento.dataTransfer.effectAllowed = 'move';
            evento.dataTransfer.setData('text/plain', card.dataset.id);
        });
        card.addEventListener('dragend', () => {
            card.classList.remove('sendo-arrastado');
            colunas.forEach((coluna) => coluna.classList.remove('arrastando-sobre'));
            cardArrastado = null;
        });
        card.querySelector('.mover-botao').addEventListener('click', () => {
            mover(card, card.querySelector('.mover-select').value);
        });
    }

    for (const coluna of colunas) {
        coluna.addEventListener('dragover', (evento) => {
            evento.preventDefault();
            evento.dataTransfer.dropEffect = 'move';
            coluna.classList.add('arrastando-sobre');
        });
        coluna.addEventListener('dragleave', (evento) => {
            if (!coluna.contains(evento.relatedTarget)) coluna.classList.remove('arrastando-sobre');
        });
        coluna.addEventListener('drop', (evento) => {
            evento.preventDefault();
            coluna.classList.remove('arrastando-sobre');
            mover(cardArrastado, coluna.dataset.destino);
        });
    }
})();
"""
