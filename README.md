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

Se a Caixa bloquear o download automático, baixe o arquivo pelo navegador em
https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_SP.csv e rode:

    python -m captacao coletar --uf SP --arquivo Lista_imoveis_SP.csv

Testes: `python tests/test_captacao.py`

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
    captacao/cli.py           comandos

Para adicionar outra fonte: criar `captacao/fontes/<nome>.py` que devolva uma lista de `ImovelCaptado`.
