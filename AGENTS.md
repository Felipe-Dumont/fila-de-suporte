# Instruções para agentes de IA

**Leia o `README.md` deste repositório antes de qualquer alteração** — em especial a
seção 2 ("Regras do projeto") e a seção 5 ("Banco de dados versionado no Git").

Resumo das restrições inegociáveis:

1. **Estrutura modular**: núcleo e servidor em `app.py`, telas em `views/`,
   configurações em `configuracao/` e rotas HTTP da API em `rotas/`.
2. **Zero dependências**: só a biblioteca padrão do Python. Nada de `pip install`,
   nada de `requirements.txt`, nada de framework.
3. **JavaScript mínimo**: use HTML + CSS e formulários por padrão. JS é reservado
   às interações que dependem dele, como arrastar cards no Kanban e copiar links.
4. **SQL sempre parametrizado** (`?`) e **toda saída escapada** com o helper `e()`.
5. **PRG nas telas**: POST de formulário responde `303`; APIs e movimentos do Kanban
   respondem JSON.
6. **Português** em código, comentários e UI.
7. **UTC no banco, `America/Sao_Paulo` na tela.**
8. **Prioridade não fura a fila** — a ordem é sempre de chegada.
9. `data.sqlite` está versionado e contém **dados reais**. Pare o app e rode o
   checkpoint do WAL antes de commitá-lo (comando na seção 5 do README).

Verificação (não há testes nem CI):

```bash
python3 -m py_compile app.py configuracao/*.py rotas/*.py views/*/*.py
python3 app.py                  # usa FILA_PORT do .env; confira a tela afetada
```
