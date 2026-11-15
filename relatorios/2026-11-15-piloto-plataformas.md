# Piloto: plataformas usadas pelos leiloeiros de SP (15/11/2026)

**Pergunta:** como um agregador chega a centenas de fontes? **Hipótese:** muitos leiloeiros
usam o mesmo software de leilão, então um leitor por plataforma cobre dezenas de sites.

**Resultado:** a hipótese se confirma. Três plataformas atendem 84 dos 203 sites lidos.

## Como foi feito

1. **Lista oficial:** uma consulta pública na JUCESP (sistema VRE, "Consultas Leiloeiro e
   Tradutor", que oferece exportação; sem captcha e sem robots.txt): **597 leiloeiros com
   situação "atuante regular"**.
2. **Domínios:** campo "Web Site" e domínio do e-mail profissional (sem Gmail, Hotmail etc.):
   311 leiloeiros com domínio próprio, **247 domínios distintos**. Os outros 286 não informam
   site ou usam e-mail genérico.
3. **Leitura:** robots.txt e página inicial de cada domínio, com pausa entre sites.
   Nenhum lote foi coletado.
4. **Assinatura do software:** servidor de scripts compartilhado, crédito "desenvolvido por",
   gerador, estrutura de pastas e formato dos endereços.

Os nomes, telefones e e-mails dos leiloeiros ficaram só na pasta temporária, fora do projeto.

## Números gerais

- 247 domínios; **203 páginas iniciais lidas**; 39 sem resposta ou com erro; **2 proíbem
  robôs** no robots.txt; nenhuma página de desafio anti-robô.
- **90 sites citam imóveis** na página inicial.

## Plataformas encontradas

| Plataforma | Sites | Com imóveis na página inicial | Como são os endereços | Observação |
|---|---|---|---|---|
| **Soleon** ("Tecnologia SOLEON") | **35** | 20 | `/leilao/<n>/lotes`, `/item/<n>` | HTML pronto. **Um adaptador cobre os 35.** |
| **leiloesjudiciais.com.br** | **19** | **19** | `/leilao/index/imoveis` | ASP.NET. Há um portal central da rede. O robots.txt do portal **proíbe percorrer páginas** (`?pagina=`) e a busca, mas libera `/api/mcp/messages` e `/auth.md`: indica **API oficial para agentes**. |
| **Degrau Publicidade e Internet** ("Sua Plataforma de Leilão") | **30** | 5 | `/lote/...` | Foco em outros bens; poucos imóveis. |
| Grupo "/eventos" (Leilão Brasil, Líder, Golden Lance...) | 9 | 6 | `/eventos/...` | Software ainda não identificado. |
| Sites React (Elance, Leilão Online, Alexandridis, Chui...) | 19 | 0 no HTML | – | Página montada por JavaScript: mais difícil, fica para depois. |
| Laravel (Zuk, Grupo Lance, Sato...) | 14 | – | – | Sistemas próprios, um adaptador cada (Zuk já está no mapa de fontes). |
| WordPress | 11 | – | – | Sites institucionais, geralmente sem catálogo de lotes. |

Um servidor de scripts aparece em 21 sites, entre eles a Mega Leilões. Deve ser um componente
comum (chat, mapa), não uma plataforma.

## Recomendação

1. **Soleon primeiro.** Com um adaptador entram 35 leiloeiros de uma vez (20 com imóveis),
   HTML pronto. Antes, conferir as regras internas do robots.txt de alguns desses sites e se a
   Soleon tem termos próprios.
2. **leiloesjudiciais.com.br pela porta da frente.** A rede tem 19 sites, todos com imóveis.
   Como o portal proíbe paginação para robôs e publica uma API para agentes, o certo é ver se
   essa API é aberta e quais são as condições de uso, ou pedir acesso. Não ler as listagens.
3. **Degrau e o grupo "/eventos"** depois, filtrando os sites que de fato têm imóveis.
4. **Fora de SP:** repetir com as Juntas de outros estados (RJ, MG, PR...). O método é o mesmo,
   e as plataformas devem se repetir, o que torna cada adaptador ainda mais valioso.

## Limites do piloto

- Só leiloeiros de SP com situação "atuante regular" e com domínio informado ou inferido pelo e-mail.
- O nome da plataforma vem do que o site declara (crédito no rodapé) e de sinais técnicos.
  Pode haver erro de agrupamento em casos isolados.
- "Cita imóveis na página inicial" é um sinal aproximado: o site pode ter imóveis em páginas internas.
