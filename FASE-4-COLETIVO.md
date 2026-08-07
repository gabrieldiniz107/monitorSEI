
# Fase 4 — Ofício COLETIVO: estado do trabalho (07/08/2026)

Objetivo: para ofício que a Anatel manda **para várias empresas de uma vez**, o bot deve
abrir → **dar ciência** → identificar ofício, anexos e prazo → baixar tudo → publicar na
pasta compartilhada com os clientes → avisar o Teams com o link.

> **Status: DESTRAVADO e validado ao vivo em 07/08/2026.** O bloqueio da §2 era um bug
> nosso (lazy-load da coluna "Ações"), não uma limitação do SEI. Ciência real dada no
> **Ofício 693** (9 empresas, 1 confirmação) e pastas publicadas para **693** e **697**.
> Falta: mandar as mensagens no Teams, deploy na VPS e cron.

---

## 1. O que está pronto

**215 testes verdes** (eram 181). Rodar: `.venv/bin/python -m pytest -q`

| Arquivo                                                                    | O que faz                                                                                                                                                  |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `seibot/coletivo.py` **(novo)**                                    | Pipeline do coletivo: seleção de candidatos,`mapear` (read-only), laço de ciência autocorretivo, download, publicação, resumo e mensagem do Teams. |
| `seibot/biblioteca.py` **(novo)**                                  | Publica na biblioteca compartilhada: cria a pasta do ofício e sobe ofício + anexos.                                                                      |
| `seibot/graph.py`                                                        | Ganhou escrita em drive:`item_do_drive`, `garantir_pasta`, `upload_arquivo`.                                                                         |
| `seibot/monitor.py`                                                      | Comando novo`coletivo --modo {mapear\|ensaio\|completo\|real}`.                                                                                             |
| `tests/test_coletivo.py`, `tests/test_biblioteca.py` **(novos)** | 24 testes.                                                                                                                                                 |

### Decisões já tomadas com você

- Entra **todo coletivo com ao menos um destinatário Pendente**, sem olhar se é cliente ativo.
- Saída é **só o Teams com o link da pasta** — nenhum e-mail/rascunho ao cliente.
- Pasta nomeada `Ofício 600 (15955558)` (nº + id do documento no SEI, porque o número
  sozinho se repete entre anos).
- **Sem card no Kanban** e fora do acompanhamento de prazos da Fase 3.
- Coletivo normalmente não tem prazo; se tiver, o bot segue e **destaca com ⚠️** no Teams.
- Resumo curto do ofício por IA na mensagem.

### Destino no SharePoint — já validado

O app **"SCM VISTORIAS"** (o mesmo que o bot já usa) **já tem acesso de escrita** à
biblioteca. Não precisa de app novo, permissão nova, nem OneDrive.

- Site `CLIENTESEPARCEIROS` → biblioteca `DOCUMENTOS` → pasta **`Ofícios Jurídicos Anatel`**
  (47 subpastas hoje, todas criadas à mão).
- Convenção que as pastas manuais usam e que o bot reproduz:
  `Ofício nº 593.pdf` + anexos `[1]-15944017_Oficio.pdf`, `[2]-15944018_Planilha.pdf`.

### Comandos criados

```bash
python -m seibot.monitor coletivo --modo ensaio               # só lista candidatos
python -m seibot.monitor coletivo --modo mapear --doc-id N    # READ-ONLY, diagnostica 1 ofício
python -m seibot.monitor coletivo --modo completo --doc-id N  # tudo, SEM ciência (já cumprido)
python -m seibot.monitor coletivo --modo real                 # produção — DÁ CIÊNCIA
```

O `real` tem as mesmas travas do individual: exige `TRATAR_AUTO=true` e só roda em dia útil,
verificados **antes** do login.

---

## 2. ✅ O BLOQUEIO — resolvido em 07/08/2026: era um bug nosso, não do SEI

A sondagem de 05/08 concluiu que, num coletivo, a página do processo não tinha **nenhum
ícone de aceite** nem o ofício na Lista de Protocolos — "não há por onde entrar". Estava
errado, e a causa era do lado do bot.

### 2.1 A coluna "Ações" não vem no HTML
Cada linha da Lista de Protocolos traz só um placeholder `<div class="md-pet-acao-lazy">`
e um loader que busca os botões por AJAX
(`controlador_ajax_externo.php?acao_ajax_externo=get_acoes_protocolo_lista`), **um documento
por vez, encadeado** (`carregarTodosDesc` percorre os placeholders em série, um `fetch` por
item, ordenados por id decrescente).

O processo do Ofício 693 tem **~105 documentos**. A cadeia leva dezenas de segundos; o
`abrir_processo` espera ~11s (1,5s + scroll + 2,5s) e lê a página antes de os ícones de
aceite existirem. `urls_aceite()` devolvia `[]`, e `[]` significa "ciência já dada" — daí a
conclusão errada. **Rolar mais não resolveria: o custo é de rede, não de viewport.**

**Correção:** `processo._aceites_lazy` chama o mesmo endpoint **em lote, uma vez**, e lê o
HTML dos botões; `urls_aceite` junta isso ao que o DOM já mostrava. Medido no 693: de 0 para
**4 ícones de aceite**.

⚠️ Isto muito provavelmente explica também as falhas silenciosas do **individual** de 03/08
(Ofício 630, `urls_aceite` vazio sem a linha "DANDO CIÊNCIA") e de 05/08 (Age
Telecomunicações) descritas no `CLAUDE.md` — mesmo mecanismo, mesmo sintoma.

### 2.2 Uma ciência cobre todo o coletivo — confirmado
No 693, **cada URL de aceite carrega os 8 `id_intimacao[]`** das empresas pendentes. Uma
confirmação cumpriu a intimação para as 9 (a R7 já constava cumprida), gerando 8 Certidões
de Intimação Cumprida novas. O laço autocorretivo de `_dar_ciencia_de_todos` deu 1 volta.

### 2.3 O padrão "R7 sempre cumprida" é a empresa acessando por conta própria
A R7 dá ciência pelo **acesso externo dela**, que é outro `id_acesso_externo`. Por isso ela
não arrasta as demais, e por isso o ofício continuava indisponível para nós até darmos a
nossa ciência. Depois dela, tudo destrava: no 697 (ciência dada pela nossa conta) o ofício
**está** na Lista de Protocolos, com os anexos.

### 2.4 Coletivo TEM prazo — e curto
A premissa "coletivo normalmente não tem prazo" caiu. Os 9 coletivos da janela são todos
**URGENTE** (`Comunica Decisão Administrativa/Judicial de Cumprimento`), com prazo de
**5 dias**: 693 → 14/08/2026, 697 → 14/08/2026. O prazo continua **fora** do acompanhamento
da Fase 3 (que depende da raia do card) e vai destacado com ⚠️ na mensagem do Teams —
decisão do usuário em 07/08, para não ampliar o escopo desta entrega.

### 2.5 O clique de ciência estoura DEPOIS de clicar
Na primeira ciência real (693), `btn.click()` estourou em
`waiting for scheduled navigations to finish` — mas o log dizia `click action done` e **a
ciência tinha entrado**. Como o erro subiu como falha comum, o checkpoint não foi gravado e
nada foi publicado; no ciclo seguinte o ofício sairia da seleção em silêncio (deixa de ter
destinatário Pendente). Correções: `no_wait_after=True` no clique e a exceção
**`processo.CienciaIncerta`**, que `tratativa`/`coletivo` tratam como *ciência dada* —
gravam o checkpoint e alertam como falha pós-ciência.

---

## 4. O que falta

1. Mandar as mensagens do Teams do 693 e do 697 (as pastas já estão publicadas).
2. Commit + deploy na VPS: `git pull` + **`docker compose build`** (produção roda da
   imagem; o compose só monta `./state`).
3. Cron do `coletivo --modo real` — sem `--doc-id`, ele trata o lote. **Hoje há 8 coletivos
   candidatos além do 693**, todos URGENTE; a primeira execução em lote dará ciência nos 8
   de uma vez. Decidir se entra assim ou um por vez.

⚠️ **Cada teste ao vivo no SEI gasta um código 2FA no e-mail do Rodrigo** e a sessão expira
em poucos minutos — juntar todas as dúvidas num teste só.

### Regra de anexos do coletivo: o que o TEXTO do ofício cita (decidido 07/08/2026)
É o **oposto** da Fase 2, que usa os documentos empacotados pelo SEI na intimação (ícones de
aceite). Motivo: no 693 o SEI empacotou 3 anexos, mas a Planilha "Tabela ISPs/Domínios"
(16075319) **não é do ofício** e não deve ir ao cliente — e o texto do ofício citava
exatamente os 2 corretos. O individual **fica como está**.

⚠️ Contrapartida aceita: ofício que esquece de citar um anexo real deixa o cliente sem ele
(foi o caso do Ofício 70, no individual — e é por isso que a Fase 2 mantém a outra regra).


---

## 5. Nota sobre o trabalho anterior (planilha de e-mails no OneDrive)

A primeira versão desta linha de trabalho implementou outra coisa (juntar os e-mails das
empresas do coletivo numa planilha no OneDrive). **Foi revertida por completo** a pedido —
não sobrou nada dela no repositório.
