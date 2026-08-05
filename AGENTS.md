# Instruções para agentes de IA

**Leia o `README.md` deste repositório antes de qualquer alteração** — em especial a
seção 2 ("Regras do projeto") e a seção 5 ("Banco de dados versionado no Git").

Resumo das restrições inegociáveis:

1. **Arquivo único**: todo o código fica em `app.py`. Não quebre em módulos.
2. **Zero dependências**: só a biblioteca padrão do Python. Nada de `pip install`,
   nada de `requirements.txt`, nada de framework.
3. **Sem JavaScript**: HTML + CSS puros, `<form>` e `<details>`.
4. **SQL sempre parametrizado** (`?`) e **toda saída escapada** com o helper `e()`.
5. **PRG**: POST responde `303` para um GET.
6. **Português** em código, comentários e UI.
7. **UTC no banco, `America/Sao_Paulo` na tela.**
8. **Prioridade não fura a fila** — a ordem é sempre de chegada.
9. `data.sqlite` está versionado e contém **dados reais**. Pare o app e rode o
   checkpoint do WAL antes de commitá-lo (comando na seção 5 do README).

Verificação (não há testes nem CI):

```bash
python3 -m py_compile app.py    # erro de sintaxe
python3 app.py                  # sobe em http://localhost:8000 e confira a tela afetada
```
