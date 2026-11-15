# Mapa de fontes (15/11/2026)

Levantamento feito lendo só o `robots.txt`, a página inicial e, nas candidatas mais fortes, os
termos de uso. Nenhum imóvel foi coletado. É uma fotografia de hoje e não é parecer jurídico:
termos e regras mudam, e a decisão de coletar é do Mateus.

Critérios: o site permite robôs? os termos proíbem coletar ou reutilizar o conteúdo? os imóveis
vêm no HTML (fácil) ou são montados por JavaScript (difícil)? que tipo de imóvel tem?

## Situação por fonte

| Fonte | robots.txt | Termos de uso | Formato da página | O que tem | Situação |
|---|---|---|---|---|---|
| Caixa (lista CSV) | – | – | CSV por estado | imóveis da Caixa | **em uso** |
| Mega Leilões | permite (só /login bloqueado); arquivos do cdn1 proíbem robôs | regulamento não fala de coleta | HTML pronto | judicial e extrajudicial (Santander, Bradesco, Itaú) | **em uso** (coleta diária liberada) |
| Zuk (portalzuk.com.br) | permite; bloqueia /edital | sem cláusula sobre coleta ou cópia | HTML pronto, 130 links de imóveis na página inicial | judicial e extrajudicial; cita Santander, Bradesco, Itaú | **pronta para virar fonte** |
| Biasi Leilões | permite tudo; tem sitemap | sem cláusula sobre coleta ou cópia | HTML pronto, sitemap | judicial e extrajudicial | **pronta para virar fonte** |
| Frazão Leilões | permite; bloqueia /Auction/Index/; tem sitemap | **não consegui ler** (texto montado por JavaScript) | HTML pronto, sitemap | imóveis de bancos (Itaú, Santander) | **Mateus confere os termos no navegador** |
| Resale (resale.com.br) | permite tudo; tem sitemap | link de termos não encontrado na página inicial | React, mas os links vêm no HTML | "outlet" de imóveis, venda direta | **Mateus confere os termos** |
| Grupo Lance (lancejudicial) | permite, exceto busca e PDFs | **cláusula 6 proíbe reprodução, distribuição ou qualquer utilização do conteúdo e das bases de dados sem autorização prévia** | HTML pronto, sitemap | muito leilão judicial com 1ª e 2ª praça | **só com autorização** (pedir parceria) |
| Superbid / Sold | sold.com.br permite, mas superbid.net responde com bloqueio anti-robô | não lido | React (sem dados no HTML) | grande plataforma, inclusive bancos | **não contornar**; só por parceria ou feed oficial |
| Sodré Santoro | página inicial bloqueia robôs (403) | não lido | – | leilões diversos | **não contornar**; só por parceria |
| Leilão Imóvel (agregador) | página bloqueia robôs (desafio anti-robô) | não lido | – | agregador de vários leiloeiros | **não contornar**; agregar agregador também tem risco |
| VIP Leilões | permite com sinal "search=yes, ai-train=no"; bloqueia robôs de IA | não lido | HTML | foco em veículos; quase nenhum imóvel na página inicial | baixa prioridade |
| Freitas Leiloeiro | sem regras | não lido | HTML | foco em veículos e materiais | baixa prioridade |

## Ordem sugerida

1. **Zuk**: grande, judicial e extrajudicial, bancos que a Mega também tem (ajuda a testar
   "mesmo imóvel em duas fontes"), robots e termos sem impedimento. Edital bloqueado no robots:
   documentos ficam como na Mega (a pessoa abre e anexa).
2. **Biasi**: sem impedimento, com sitemap (descoberta de imóveis mais simples que listagens).
3. **Frazão** e **Resale**: assim que o Mateus conferir os termos no navegador.
4. **Grupo Lance, Superbid/Sold, Sodré Santoro**: pedir autorização ou feed oficial. A rede
   comercial do João pode abrir essas portas; um acordo dá dados mais estáveis que ler páginas.

Com Mega, Zuk e Biasi já entra boa parte dos imóveis de Santander, Bradesco e Itaú, porque
esses bancos vendem por leiloeiros.

## O que cada fonte nova custa

Um adaptador em `captacao/adaptadores/fontes/`, uma linha em `montagem.FONTES` e uma página de
amostra no teste de contrato. Cliente web educado, modelo de leilão, tela e simulador já servem
para qualquer fonte. Quando houver duas fontes com os mesmos imóveis, entra a separação
Imóvel × Anúncio para juntar duplicados.

## Regras que valem para todas

- Respeitar robots.txt, uma rodada por dia, 3 s entre pedidos, identificação genérica.
- Nunca contornar bloqueio anti-robô (403, desafio "Just a moment").
- Documentos (edital, matrícula) só automáticos onde o robots permitir; nos outros, a pessoa
  baixa e anexa.
- Rever robots e termos de cada fonte de tempos em tempos.
