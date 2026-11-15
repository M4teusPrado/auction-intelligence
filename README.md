# Captação de imóveis (primeiro bloco do Auction Intelligence)

Coleta imóveis de uma fonte, guarda numa base única (SQLite) e registra o que mudou entre uma coleta e outra.
Primeira fonte: a lista pública de imóveis da Caixa, um arquivo CSV por estado.
Só usa Python 3.9+ e a biblioteca padrão: não precisa instalar nada.

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

Testes: `for t in tests/test_*.py; do python3 $t; done`

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

## Estrutura

    captacao/modelo.py        formato comum de imóvel, igual para toda fonte
    captacao/normaliza.py     limpeza de números e endereços
    captacao/fontes/caixa.py  download e leitura da lista da Caixa
    captacao/repositorio.py   base SQLite, histórico e duplicados
    captacao/classifica.py    categoria e alertas derivados (não alteram a fonte)
    captacao/triagem.py       funções da API da tela (filtros, resumo, triagem)
    captacao/ficha.py         ficha do imóvel: investigação, anexos, simulações salvas
    captacao/simulador.py     conta de custos e retorno (regra fixa)
    captacao/tela.py          servidor local da tela
    captacao/web/index.html   a tela (HTML, CSS e JS num arquivo só)
    captacao/cli.py           comandos
    ferramentas/              scripts de manutenção da base

Para adicionar outra fonte: criar `captacao/fontes/<nome>.py` que devolva uma lista de `ImovelCaptado`.
