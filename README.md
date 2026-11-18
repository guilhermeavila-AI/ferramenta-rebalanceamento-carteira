# Ferramenta de rebalanceamento de carteira

Mostra, em R$, quanto cada ativo e cada classe da carteira de investimentos está acima ou abaixo da meta.

**Experimente:** https://rebalanceamento-carteira.streamlit.app/

> Os dados do exemplo são **fictícios**. A primeira abertura do link pode demorar alguns segundos: no plano gratuito do Streamlit o app "dorme" depois de um tempo sem acesso e acorda quando alguém o abre.

## O problema

Para manter minha carteira equilibrada, eu atualizava uma planilha na mão. Os saldos ficam em lugares diferentes: a reserva de caixa, uma conta nos EUA, que eu convertia pelo dólar do dia, e a corretora brasileira. Eu somava tudo, olhava ativo por ativo quanto havia de dinheiro e só então decidia o que comprar e o que vender. A cada ordem, tinha que refazer as contas.

Esta ferramenta faz esse trabalho: lê a carteira e as metas de um arquivo CSV, busca os preços e o dólar do dia, calcula tudo em R$ e mostra, ativo por ativo e classe por classe, o que está acima ou abaixo da meta. Depois de cada compra ou venda, basta registrar a movimentação e o painel se atualiza na hora.

## O que a ferramenta faz

O menu no topo tem cinco páginas:

| Página | Para que serve |
|---|---|
| **Visão geral** | Patrimônio total, um cartão por classe e a tabela por classe, com a situação de cada uma. Botões para carregar a carteira, atualizar preços, registrar movimentações e baixar a carteira. |
| **Visão por ativo** | Cada ativo (ou só os de uma classe): quantidade, preço, valor em R$, percentual atual, meta e diferença. |
| **Registrar movimentações** | Compra, venda, aporte e retirada de caixa, por formulário. Compra e venda podem ser informadas por quantidade ou por valor em R$. O caixa se ajusta sozinho. |
| **Preços** | O que o Yahoo Finance devolveu, com a data de cada preço. Se algum preço falhar, dá para digitar na mão. |
| **Minha carteira** | Carregar um CSV, baixar a carteira atualizada, ver a carteira e as metas e conferir se as metas somam 100%. |

**Cores.** Vermelho: abaixo da meta (falta comprar). Verde: acima da meta. Azul: na meta, ou seja, a diferença é de até R$ 100 para mais ou para menos. A coluna "Situação" também escreve o estado em palavras.

**Termos.** *Meta*: quanto da carteira cada classe ou ativo deveria ter, em %. *Caixa*: o dinheiro parado na carteira, disponível para comprar ativos. *Fundo imobiliário*: fundo que investe em imóveis e negocia em bolsa (FII). *Diferença*: valor atual menos a meta; positivo é acima, negativo é abaixo.

## O arquivo da carteira (CSV)

A carteira tem estas colunas:

| Coluna | O que é |
|---|---|
| `ativo` | Nome do ativo na tela (ex.: `PETR4 - Petrobras`). A linha do caixa se chama `Caixa`. |
| `codigo_yahoo` | Código do ativo no Yahoo Finance (ex.: `PETR4.SA`; vazio para o Caixa). |
| `classe` | Classe do ativo. Precisa existir no arquivo de metas. |
| `quantidade` | Quantidade que a carteira tem (no Caixa, o valor em R$). |
| `moeda` | `BRL` ou `USD`. Ativos em dólar são convertidos pelo dólar do dia. |
| `meta_na_classe_pct` | Meta do ativo dentro da classe, em %. Dentro de cada classe, a soma deve dar 100. |

O arquivo `metas_classe.csv` tem as colunas `classe` e `meta_pct` (a soma deve dar 100).

Ao carregar um arquivo, a ferramenta confere colunas, ativos repetidos, classes sem meta, moeda, números e ativos sem código do Yahoo. Se houver erro, mostra o motivo e mantém a carteira atual.

## Limitações

- **Preços.** Vêm do Yahoo Finance pela biblioteca yfinance, que é gratuita e não oficial. Podem atrasar ou divergir da corretora e, fora do pregão, podem ser os da sessão anterior. A ferramenta mostra a data de cada preço e avisa quando está velho. O Yahoo funcionou na nuvem no teste de 17/11/2026, mas pode limitar pedidos feitos por servidores compartilhados; se isso acontecer, dá para digitar o preço.
- **O formulário usa o preço da tabela de preços**, e não o preço real da ordem na corretora. Pequenas diferenças se acumulam, então vale conferir com a corretora de tempos em tempos.
- **As metas por classe são fixas no app público.** Só a carteira pode ser carregada pela tela; as classes e metas vêm do arquivo `metas_classe.csv` do repositório (Ação, Fundo imobiliário, Exterior e Caixa). Uma carteira com outra classe, ou com o nome antigo (como "FII"), é recusada com uma mensagem que lista as classes válidas, e a carteira atual é mantida. Para usar outras classes ou metas, altere o `metas_classe.csv` e rode no seu computador.
- **Nada fica salvo.** A carteira vive na memória enquanto a página está aberta. Para guardar as movimentações, baixe o CSV e carregue-o na próxima vez. O app público não deve receber dados reais: para dados reais, rode no seu computador.
- **A faixa de "na meta" é fixa em R$ 100**, não muda com o tamanho da carteira.
- **Celular.** O layout foi pensado para tela larga e não é adaptado para celular: a primeira tela mostra o título, o texto de apresentação, o menu e o começo do "Como usar", e os botões e os números do painel ficam abaixo, com rolagem. Funciona, mas não é confortável. Ainda a resolver.
- **Esta versão não usa IA na ferramenta.** Só a construção usou.

## Rodar no seu computador (opcional)

Não é necessário para usar o app: o link acima já funciona no navegador. Estes passos servem para quem quer rodar uma cópia local, por exemplo com dados reais. Precisa ter o Python instalado. Rode os comandos na pasta do projeto:

```
pip install -r requirements.txt
streamlit run app.py
```

Tecnologias: Python, Streamlit, pandas, yfinance e CSV.

## Como foi construído

Esta ferramenta foi **construída com auxílio de IA (Claude, da Anthropic)**, passo a passo: uma etapa por vez, com explicação e teste a cada passo. Eu decidi o que construir, o que cortar, os dados de exemplo, as regras e o visual, testei na tela e apontei o que estava ruim de usar. A IA escreveu o código.

**Como foi testado.** Em duas frentes. (1) Testes automáticos, com preços fixos e uma versão simulada do Streamlit: cobrem os cálculos, o formulário e o baixar e carregar do CSV, e comparam os resultados do app com uma segunda conta, escrita à parte de forma simples. (2) Uso real do app publicado, no computador e no celular, que é onde aparece o que depende do Yahoo e da aparência. Os testes automáticos não substituem o uso real: nenhum deles chama o Yahoo.

## O que deu errado e o que aprendi

- Os preços da bolsa brasileira vieram do pregão anterior num teste feito de madrugada. Minha primeira explicação estava errada; o teste de diagnóstico mostrou o que acontecia. Agora a ferramenta mostra a data de cada preço, avisa quando está velho e permite digitar na mão.
- Os testes automáticos do formulário passaram, mas na tela real o campo de número bagunçava o que eu digitava e não aceitava vírgula. Corrigi depois de testar usando de verdade.
- Ao testar no celular, vi que o layout todo foi pensado para tela larga e não se adapta bem a telas pequenas (a primeira tela, por exemplo, mostra pouca coisa útil sem rolar). Registrei como limitação e como possível melhoria.

## Possíveis melhorias

- Adaptar o layout para celular.
- Função de IA para registrar movimentações em texto livre (por exemplo, "vendi 50 BBAS3"), com confirmação antes de salvar.
- Gráficos (meta x atual) e um resumo do que comprar ou vender.
- Baixar também o histórico de movimentações e salvar a carteira automaticamente.
- Fonte de preços paga ou oficial.
- Avaliar uma tecnologia ou uma plataforma de publicação mais adequada a um app de uso diário (por exemplo, com layout para celular e com a carteira salva).

## Versões

- **v1.1 (17/11/2026):** menu com cinco páginas e botões de atalho na página inicial, explicação de uso, avisos (dados fictícios e movimentações não baixadas), tema claro e escuro, letras maiores e carteira de exemplo simplificada.
- **v1.0 (17/11/2026):** primeira versão publicada, com painel colorido, formulário de movimentações e baixar e carregar a carteira em CSV.

## Licença

MIT (arquivo `LICENSE`). Projeto de portfólio, com dados fictícios.
