# Captação de imóveis (primeiro bloco do Auction Intelligence)

Coleta imóveis de uma fonte, guarda numa base única (SQLite) e registra o que mudou entre uma coleta e outra.
Primeira fonte: a lista pública de imóveis da Caixa, um arquivo CSV por estado.
Usa Python 3.9+ e a biblioteca padrão. A única dependência opcional é `pypdf`, que liga a
leitura dos PDFs anexados (matrícula, edital). Para instalar, uma vez, na pasta do projeto:

    python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt

Depois use `.venv/bin/python` no lugar de `python3` nos comandos abaixo. Sem o pypdf tudo
funciona, só a leitura de PDF fica desligada.

## Fontes

- **caixa**: lista pública da Caixa (CSV por estado).
- **megaleiloes**: Mega Leilões, leilões judiciais e extrajudiciais (Santander, Bradesco,
  Itaú...). Coleta diária liberada pelo Mateus em 15/11/2026, depois de conferir robots.txt
  e regulamento. O servidor de arquivos da Mega (cdn1) proíbe robôs no robots.txt: edital e
  matrícula são baixados pela pessoa no navegador e anexados na ficha.
- **soleon**: 35 leiloeiros que usam a plataforma Soleon (achados pela lista da JUCESP).
  Recorte = site do leiloeiro. Coleta diária liberada pelo Mateus em 15/11/2026 (robots.txt
  permite; a plataforma não publica termos de uso). PDFs em servidor que proíbe robôs: links.

    python -m captacao fontes                                      # lista as fontes
    python -m captacao coletar --fonte soleon --recorte todos      # os 35 sites, um por vez (~1 h)
    python -m captacao coletar --fonte megaleiloes --recorte SP    # coleta diária (20-40 min)
    python -m captacao importar <link de uma oferta>               # imóvel avulso

O acesso à web (`adaptadores/web.py`) respeita robots.txt e Crawl-delay, espera 3 s entre
pedidos ao mesmo site e guarda cópia local das páginas em `cache_web/` por 20 h.
Coleta incompleta (limite, página com erro) não marca ninguém como "saiu da lista".

## Como usar

    python -m captacao coletar --uf SP
    python -m captacao listar --uf SP --cidade campinas --tipo terreno --desconto-min 30
    python -m captacao novidades
    python -m captacao duplicados
    python -m captacao exportar imoveis.csv
    python -m captacao tela                 # tela de triagem em http://127.0.0.1:8765/

Se a Caixa bloquear o download automático, baixe o arquivo pelo navegador em
https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_SP.csv e rode:

    python -m captacao coletar --uf SP --arquivo Lista_imoveis_SP.csv

Testes: `for t in tests/test_*.py; do .venv/bin/python $t; done`

## Tela de triagem

`python -m captacao tela` sobe um servidor local (só em 127.0.0.1, porta 8765; outra com
`--porta`) e abre o navegador. Funciona sem internet. Cada imóvel passa pelos estágios
identificado (na fila), analisar, depois e descartado; toda mudança fica na tabela
`triagens` e desfazer grava uma linha nova, nada é apagado. Ctrl+C no terminal encerra.

Clicar no imóvel abre a ficha: dados da fonte, checklist de investigação, anexos (PDF/PNG/JPG
baixados pelo navegador, salvos em `anexos/` ao lado da base), histórico e o simulador de
custos e retorno. O simulador é conta fixa (`captacao/simulador.py`); as premissas padrão são
exemplos a confirmar e o valor de venda não tem padrão, porque a avaliação da Caixa não é
valor de mercado.

Na investigação, cada item tem atalhos (mapa, página da Caixa, matrícula online, IPTU), uma
lista do que procurar e, quando há PDF anexado, os trechos encontrados por busca de palavras
(`captacao/documentos.py`), com documento e página. São trechos para ler, não conclusões.

**Parecer preliminar com IA** (botão na etapa Investigar, aprovado em 15/11/2026): a IA (Claude,
`adaptadores/ia/claude.py`) lê a descrição do lote e os PDFs anexados e sugere a situação de cada
item, os riscos e o que falta apurar, sempre com documento, página e trecho. O trecho é conferido
no texto por regra fixa (`dominio/parecer.py`); o que não existir aparece como "não confirmado".
CPF e RG são mascarados antes do envio. Nada é marcado sozinho: a pessoa usa ou não a sugestão.
Custa cerca de US$ 0,15 por análise. Precisa de credencial da Anthropic (`ANTHROPIC_API_KEY`
ou `ant auth login`); sem ela, a tela mostra o motivo.

**PDF escaneado** (matrícula em imagem, comum na Caixa): o botão "Ler PDF escaneado com IA" no
arquivo manda o PDF original para o Claude transcrever página por página (aprovado em 15/11/2026,
~US$ 0,10–0,30 por documento, uma vez só). A imagem vai inteira (não dá para mascarar antes); a
transcrição guardada tem CPF e RG mascarados e passa a valer para a busca de trechos e o parecer,
marcada como "transcrição por IA".

## O que ele faz

- Guarda cada imóvel com a fonte, o identificador na fonte, o link e as datas da primeira e da última vez em que apareceu.
- A cada coleta registra no histórico: imóvel novo, campo alterado (preço, avaliação, desconto, modalidade), imóvel que saiu da lista e imóvel que voltou.
- Sugere possíveis duplicados pelo endereço normalizado. É só sugestão: uma pessoa confirma.
- Linhas com problema viram aviso, não dado errado. Coleta vazia não marca a base inteira como "saiu da lista".

## Limites conhecidos

- O formato real do CSV da Caixa NÃO foi conferido neste ambiente (sem acesso à internet). O arquivo `tests/exemplo_caixa.csv` é fictício. O leitor acha as colunas pelo nome e dá erro claro se faltar alguma obrigatória.
- "Valor de avaliação" é o da fonte, não o valor de mercado.
- Tipo e áreas são extraídos da descrição por melhor esforço.
- Antes de automatizar coletas frequentes, confira os termos de uso do site da Caixa. Uma coleta por dia por estado é suficiente.

## Arquitetura (hexagonal, um monolito só)

As regras ficam no centro e não conhecem banco, rede, arquivo nem tela. O resto se liga
por portas (interfaces Python), e `montagem.py` é o único lugar que escolhe as peças.

    captacao/dominio/          regras puras: modelo do imóvel, normalização, categoria e
                               alertas, simulador, vocabulário da análise (estágios, itens)
    captacao/aplicacao/        casos de uso: coletar, triagem, ficha
      portas.py                FonteDeImoveis, RepositorioDeImoveis, RepositorioDeAnalise...
    captacao/adaptadores/
      fontes/caixa.py          a lista da Caixa como FonteDeImoveis
      persistencia/sqlite.py   único lugar com SQL; migração com cópia da base
    captacao/montagem.py       registro das fontes (FONTES) e abertura do banco
    captacao/cli.py            comandos (entrada)
    captacao/tela.py + web/    tela local (entrada)
    captacao/documentos.py     leitura de PDF e busca de trechos (vira porta na próxima etapa)
    ferramentas/               scripts de manutenção da base

Regra de dependência: `dominio` não importa nada do projeto; `aplicacao` importa só
`dominio` e as portas; adaptadores e entradas podem importar tudo.

### Como criar uma fonte nova

1. Crie `captacao/adaptadores/fontes/<nome>.py` com uma classe que tenha `nome`, `descricao`,
   `recortes()`, `coletar(recorte, arquivo, nome_arquivo)` e `descrever_modalidade(modalidade)`
   (veja a porta `FonteDeImoveis` em `aplicacao/portas.py` e o exemplo `FonteCaixa`).
   Devolva `Coleta` com imóveis no formato `ImovelCaptado`; linha com problema vira aviso;
   falha de acesso ou formato vira `ErroDeFonte`.
2. Registre em `montagem.FONTES`.
3. Salve um arquivo de exemplo em `tests/` e acrescente em `AMOSTRAS` de
   `tests/test_contrato_fontes.py`. O teste de contrato roda para toda fonte registrada.
4. Antes de coletar de um site, confira os termos de uso. Uma coleta por dia por recorte.

Coleta de qualquer fonte: `python -m captacao coletar --fonte <nome> --recorte <recorte>`.

**Documentos automáticos ao marcar "Para analisar"** (decisão do Mateus, 15/11/2026): ao entrar
em "Para analisar", a tela baixa sozinha, em segundo plano, os documentos publicados pela fonte
(edital, matrícula, laudo) e anexa à ficha. É download sob demanda, um pedido por documento e
só para imóveis escolhidos por uma pessoa: nesse caso o robots.txt do servidor de arquivos não
impede o pedido (Mega, Soleon), mas o ritmo e a identificação continuam valendo. Na Caixa, a
matrícula fica em endereço previsível pelo número do imóvel e costuma ser escaneada (use "Ler
PDF escaneado com IA"). O edital da Caixa é um PDF único que lista
centenas de imóveis pelo número: cole o link dele uma vez (na ficha, ou
`python -m captacao edital-caixa <url>`) e o sistema liga o edital a todos os imóveis da base que
aparecem nele, anexando nos que estão em "Para analisar".

**Custo da IA (decisão do Mateus, 16/11/2026, após teste comparativo):** parecer com
claude-sonnet-5-5 (esforço médio), ~US$ 0,08–0,15 por imóvel; regras gerais de cada edital
coletivo (Caixa) lidas uma vez com claude-opus-5-5 (~US$ 0,26 por edital, reaproveitadas por
todos os imóveis dele); transcrição de PDF escaneado com claude-haiku-5-5 (< US$ 0,01 por
matrícula). Antes: ~US$ 1,00 por imóvel com edital da Caixa.
