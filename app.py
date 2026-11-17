# app.py - Ferramenta de rebalanceamento de carteira
# Etapa 3, itens 1 a 6: ler a carteira e as metas, buscar preços e dólar, calcular valores em R$,
# mostrar o painel colorido (acima / abaixo da meta), registrar movimentações por formulário
# (compra, venda, aporte e retirada de caixa) e baixar / carregar a carteira em CSV.

from datetime import date  # para saber a data de hoje
from pathlib import Path  # ajuda a encontrar os arquivos na mesma pasta do app

import pandas as pd  # biblioteca para trabalhar com tabelas
import streamlit as st  # biblioteca que transforma este script em uma página web
import yfinance as yf  # biblioteca que busca preços no Yahoo Finance

# Pasta onde este arquivo (app.py) está guardado.
PASTA = Path(__file__).parent

# Colunas que cada CSV precisa ter. Se faltar alguma, o app avisa em vez de quebrar.
COLUNAS_CARTEIRA = ["ativo", "codigo_yahoo", "classe", "quantidade", "moeda", "meta_na_classe_pct"]
COLUNAS_METAS = ["classe", "meta_pct"]

# Código do dólar no Yahoo: quantos reais vale 1 dólar.
CODIGO_DOLAR = "BRL=X"

# Se o último preço tiver mais dias que isso, o app avisa que pode estar velho.
# (Fim de semana e feriado explicam até uns 4 dias.)
DIAS_PARA_AVISAR = 4


def ler_tabela(caminho, colunas_esperadas):
    """Lê um arquivo CSV e confere se ele tem as colunas esperadas."""
    tabela = pd.read_csv(caminho, encoding="utf-8")
    faltando = [c for c in colunas_esperadas if c not in tabela.columns]
    if faltando:
        raise ValueError(f"{Path(caminho).name}: faltam as colunas {', '.join(faltando)}")
    return tabela


def conferir_metas(carteira, metas):
    """Devolve uma lista de avisos. Lista vazia = está tudo certo."""
    avisos = []

    # 1) As metas das classes (Ação, FII...) devem somar 100%.
    soma_classes = metas["meta_pct"].sum()
    if abs(soma_classes - 100) > 0.01:
        avisos.append(f"As metas por classe somam {soma_classes:g}%, e deveriam somar 100%.")

    # 2) Dentro de cada classe, as metas dos ativos devem somar 100%.
    soma_por_classe = carteira.groupby("classe")["meta_na_classe_pct"].sum()
    for classe, soma in soma_por_classe.items():
        if abs(soma - 100) > 0.01:
            avisos.append(f"Na classe {classe}, as metas dos ativos somam {soma:g}%, e deveriam somar 100%.")

    # 3) Toda classe da carteira precisa ter uma meta em metas_classe.csv (e vice-versa).
    so_na_carteira = set(carteira["classe"]) - set(metas["classe"])
    so_nas_metas = set(metas["classe"]) - set(carteira["classe"])
    if so_na_carteira:
        avisos.append("Classes sem meta: " + ", ".join(sorted(so_na_carteira)))
    if so_nas_metas:
        avisos.append("Classes com meta mas sem ativos: " + ", ".join(sorted(so_nas_metas)))

    return avisos


def validar_carteira(tabela, metas):
    """Confere uma carteira vinda de um CSV enviado pela pessoa.
    Devolve (tabela_limpa, None) se estiver tudo certo, ou (None, mensagem_de_erro)."""
    faltando = [c for c in COLUNAS_CARTEIRA if c not in tabela.columns]
    if faltando:
        return None, "Faltam as colunas: " + ", ".join(faltando) + "."
    t = tabela[COLUNAS_CARTEIRA].copy()
    if t.empty:
        return None, "O arquivo não tem nenhuma linha."

    # Textos: tira espaços e troca vazio por "".
    for coluna in ["ativo", "codigo_yahoo", "classe", "moeda"]:
        t[coluna] = t[coluna].fillna("").astype(str).str.strip()

    if (t["ativo"] == "").any():
        return None, "Há linhas sem nome de ativo."
    repetidos = sorted(t.loc[t["ativo"].duplicated(), "ativo"].unique())
    if repetidos:
        return None, "Ativos repetidos: " + ", ".join(repetidos) + "."
    if (t["classe"] == "").any():
        return None, "Há ativos sem classe."
    desconhecidas = sorted(set(t["classe"]) - set(metas["classe"]))
    if desconhecidas:
        return None, ("Classes que não existem no arquivo de metas: " + ", ".join(desconhecidas)
                      + ". Classes válidas: " + ", ".join(metas["classe"]) + ".")
    moedas_ruins = sorted(set(t["moeda"]) - {"BRL", "USD"})
    if moedas_ruins:
        return None, "Moeda inválida (só BRL ou USD): " + ", ".join(moedas_ruins) + "."

    # Todo ativo, menos o Caixa, precisa de código do Yahoo (sem código o app assumiria preço 1).
    sem_codigo = t.loc[(t["codigo_yahoo"] == "") & (t["ativo"] != "Caixa"), "ativo"].tolist()
    if sem_codigo:
        return None, "Falta o código do Yahoo em: " + ", ".join(sem_codigo) + "."

    # Números: quantidade e meta dentro da classe.
    for coluna in ["quantidade", "meta_na_classe_pct"]:
        t[coluna] = pd.to_numeric(t[coluna], errors="coerce")
        if t[coluna].isna().any():
            return None, (f"A coluna {coluna} tem valores que não são números "
                          "(use ponto como decimal no CSV, ex.: 0.5).")
    if (t["quantidade"] < 0).any():
        return None, "Há quantidades negativas."
    if ((t["meta_na_classe_pct"] < 0) | (t["meta_na_classe_pct"] > 100)).any():
        return None, "A meta dentro da classe precisa estar entre 0 e 100."
    return t.reset_index(drop=True), None


def calcular(carteira, metas, tabela_precos, dolar):
    """Calcula tudo em R$. Devolve (tabela por ativo, tabela por classe, patrimônio total).

    Diferença = valor atual - valor da meta.
      positivo -> acima da meta (sobrou);  negativo -> abaixo da meta (falta comprar).
    """
    desconhecidas = set(carteira["moeda"]) - {"BRL", "USD"}
    if desconhecidas:
        raise ValueError("moeda desconhecida na carteira: " + ", ".join(sorted(desconhecidas)))

    # Junta o preço de cada ativo à carteira.
    dados = carteira.merge(tabela_precos[["ativo", "preco"]], on="ativo", how="left")

    # Valor em R$ = quantidade x preço (x dólar, se o ativo é cotado em dólar).
    cambio = dados["moeda"].map({"BRL": 1.0, "USD": dolar})
    dados["valor_rs"] = dados["quantidade"] * dados["preco"] * cambio
    patrimonio = dados["valor_rs"].sum()

    # ---- por classe: quanto a classe vale hoje x quanto deveria valer ----
    por_classe = dados.groupby("classe", as_index=False)["valor_rs"].sum()
    por_classe = metas.merge(por_classe, on="classe", how="left").fillna({"valor_rs": 0.0})
    por_classe["pct_atual"] = por_classe["valor_rs"] / patrimonio * 100
    por_classe["meta_rs"] = por_classe["meta_pct"] / 100 * patrimonio
    por_classe["diferenca_rs"] = por_classe["valor_rs"] - por_classe["meta_rs"]

    # ---- por ativo: a meta do ativo é (meta da classe) x (meta do ativo dentro da classe) ----
    dados = dados.merge(metas, on="classe", how="left")
    dados["pct_atual"] = dados["valor_rs"] / patrimonio * 100
    dados["meta_pct_total"] = dados["meta_pct"] * dados["meta_na_classe_pct"] / 100
    dados["meta_rs"] = dados["meta_pct_total"] / 100 * patrimonio
    dados["diferenca_rs"] = dados["valor_rs"] - dados["meta_rs"]
    por_ativo = dados[["ativo", "classe", "quantidade", "preco", "moeda", "valor_rs",
                       "pct_atual", "meta_pct_total", "meta_rs", "diferenca_rs"]]

    return por_ativo, por_classe, patrimonio


def formata_rs(valor):
    """Escreve um número no formato brasileiro: R$ 1.234,56."""
    texto = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if valor < 0 else "R$ ") + texto


# Diferenças menores que isto (em R$) contam como "na meta", para não pintar de vermelho por centavos.
TOLERANCIA_RS = 1.0

# Cor de fundo de cada situação (o texto fica sempre escuro, para ler bem no tema claro e no escuro).
CORES = {
    "Abaixo da meta": "background-color: #f8d7da; color: #1a1a1a",  # vermelho claro: falta comprar
    "Acima da meta": "background-color: #cfe2ff; color: #1a1a1a",   # azul claro: passou da meta
    "Na meta": "background-color: #d1e7dd; color: #1a1a1a",         # verde claro: ok
}


def situacao(diferenca):
    """Diz em palavras se o valor está acima, abaixo ou na meta."""
    if diferenca > TOLERANCIA_RS:
        return "Acima da meta"
    if diferenca < -TOLERANCIA_RS:
        return "Abaixo da meta"
    return "Na meta"


def formata_pct(valor):
    """Escreve uma porcentagem no formato brasileiro: 12,3%."""
    return f"{valor:.1f}%".replace(".", ",")


def formata_preco(valor):
    """Preço com 2 casas e vírgula decimal: 1.234,56 (sem o R$, porque pode estar em dólar)."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formata_quantidade(valor):
    """Quantidade sem zeros sobrando e com vírgula decimal: 150 ou 0,279."""
    return f"{valor:g}".replace(".", ",")


def tabela_colorida(tabela, colunas_rs, colunas_pct):
    """Recebe uma tabela com as colunas "Situação" e "Diferença (R$)" e devolve uma versão
    com números no formato brasileiro e as duas colunas pintadas conforme a situação."""
    def pintar_linha(linha):
        cor = CORES[linha["Situação"]]
        return [cor if coluna in ("Situação", "Diferença (R$)") else "" for coluna in linha.index]

    formatos = {coluna: formata_rs for coluna in colunas_rs}
    formatos.update({coluna: formata_pct for coluna in colunas_pct})
    if "Preço" in tabela.columns:  # preço na moeda do ativo
        formatos["Preço"] = formata_preco
    if "Quantidade" in tabela.columns:  # quantidade sem zeros sobrando (150 em vez de 150.000000)
        formatos["Quantidade"] = formata_quantidade
    return tabela.style.apply(pintar_linha, axis=1).format(formatos)


@st.cache_data(ttl=900, show_spinner=False)  # guarda a resposta por 15 min, para não ficar chamando o Yahoo
def buscar_preco(codigo):
    """Busca o último preço de um código no Yahoo. Devolve (preço, data) ou (None, None) se falhar."""
    try:
        historico = yf.Ticker(codigo).history(period="5d")
        historico = historico.dropna(subset=["Close"])  # descarta dias sem preço
        if historico.empty:
            return None, None
        return float(historico["Close"].iloc[-1]), historico.index[-1].date()
    except Exception:
        return None, None  # qualquer erro vira "sem preço"; o app oferece o plano B manual


# ---------------------------------------------------------------------------
# A partir daqui é a página que a pessoa vê.
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Rebalanceamento de carteira", layout="wide")
st.title("Rebalanceamento de carteira")
st.caption("Versão em construção. Dados fictícios de exemplo.")

# Tenta ler os dois arquivos. Se algo der errado, mostra o motivo na tela.
try:
    carteira = ler_tabela(PASTA / "carteira_exemplo.csv", COLUNAS_CARTEIRA)
    metas = ler_tabela(PASTA / "metas_classe.csv", COLUNAS_METAS)
except Exception as erro:
    st.error(f"Não consegui ler os arquivos: {erro}")
    st.stop()  # para aqui: sem os arquivos não há o que mostrar

# A carteira fica guardada na "sessão" (a memória do app enquanto a página está aberta).
# Assim as movimentações registradas continuam valendo a cada atualização da tela.
# Atenção: se a página for recarregada (F5), volta para o arquivo de exemplo.
if "carteira" not in st.session_state:
    st.session_state["carteira"] = carteira  # cópia de trabalho, vinda do CSV
    st.session_state["movimentacoes"] = []   # lista do que foi registrado nesta sessão
carteira = st.session_state["carteira"]

st.subheader("Carteira")
if st.session_state.get("aviso_carteira"):  # mensagem da última carga (a tela é recarregada depois de carregar)
    st.success(st.session_state.pop("aviso_carteira"))
st.dataframe(carteira, hide_index=True)

# --- Item 6: baixar a carteira atualizada e carregar uma própria ---
with st.expander("Salvar ou carregar a carteira (CSV)", expanded=False):
    st.markdown("**Salvar:** baixe a carteira com as suas movimentações. Ao recarregar a página, "
                "o app volta ao exemplo; para continuar de onde parou, carregue o arquivo baixado.")
    # utf-8-sig: o Excel no Windows abre com os acentos certos (Ação) e o app consegue ler de volta.
    csv_atual = carteira[COLUNAS_CARTEIRA].to_csv(index=False, float_format="%.10g").encode("utf-8-sig")
    st.download_button("Baixar carteira atualizada (CSV)", data=csv_atual,
                       file_name="carteira_atualizada.csv", mime="text/csv")

    st.markdown("**Carregar:** envie um CSV com as colunas " + ", ".join(COLUNAS_CARTEIRA) + ". "
                "As metas por classe continuam as do arquivo metas_classe.csv.")
    st.caption("Atenção: este app é público. Para dados reais, prefira rodar o app no seu computador; "
               "aqui use dados fictícios. O app não grava a carteira em arquivo: ela fica só na memória "
               "enquanto a página está aberta.")
    arquivo = st.file_uploader("Carteira em CSV (um arquivo por vez)", type="csv")
    st.caption("Passo 1: escolha o arquivo. Passo 2: clique em \"Usar esta carteira\". "
               "O \"+\" ao lado do nome serve para trocar o arquivo, não para juntar vários.")
    if arquivo is not None and st.button("Usar esta carteira"):
        try:
            nova, erro_csv = validar_carteira(pd.read_csv(arquivo, encoding="utf-8-sig"), metas)
        except Exception as erro:  # arquivo que nem é um CSV legível
            nova, erro_csv = None, f"Não consegui ler o arquivo: {erro}"
        if erro_csv:
            st.error(erro_csv + " A carteira atual foi mantida.")
        else:
            st.session_state["carteira"] = nova
            st.session_state["movimentacoes"] = []
            st.session_state["aviso_carteira"] = f"Carteira carregada: {len(nova)} linhas."
            st.rerun()
    if st.button("Voltar para a carteira de exemplo"):
        st.session_state["carteira"] = ler_tabela(PASTA / "carteira_exemplo.csv", COLUNAS_CARTEIRA)
        st.session_state["movimentacoes"] = []
        st.session_state["aviso_carteira"] = "Voltou para a carteira de exemplo."
        st.rerun()

st.subheader("Metas por classe")
st.dataframe(metas, hide_index=True)

# Mostra se as metas fazem sentido (somam 100%).
avisos = conferir_metas(carteira, metas)
if avisos:
    for aviso in avisos:
        st.warning(aviso)
else:
    st.success("Conferência das metas: tudo certo (cada nível soma 100%).")


# ---------------------------------------------------------------------------
# Item 2: preços e dólar
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Preços")
st.caption("Último preço disponível no Yahoo Finance, com a data de cada um. Durante o pregão é o preço do momento "
           "(com pequeno atraso); fora dele, o fechamento. Ativos em dólar mostram o preço em dólar; "
           "a conversão para R$ vem no próximo passo.")

# Botão para esquecer o que foi guardado e buscar tudo de novo.
if st.button("Atualizar preços"):
    buscar_preco.clear()

with st.spinner("Buscando preços no Yahoo Finance..."):
    dolar, data_dolar = buscar_preco(CODIGO_DOLAR)
    consultas = {}  # ativo -> (preço, data)
    for _, linha in carteira.iterrows():
        codigo = linha["codigo_yahoo"]
        if pd.isna(codigo) or str(codigo).strip() == "":
            continue  # o Caixa não tem código: o preço dele é 1
        consultas[linha["ativo"]] = buscar_preco(str(codigo).strip())

sem_preco = [ativo for ativo, (preco, _) in consultas.items() if preco is None]

# Plano B: o que o Yahoo não devolveu, a pessoa digita.
dolar_fonte = "Yahoo"
precos_manuais = {}
if dolar is None or sem_preco:
    st.warning("O Yahoo não devolveu alguns preços. Digite abaixo o que faltou "
               "(ou clique em 'Atualizar preços' para tentar de novo).")
    with st.expander("Digitar preços manualmente", expanded=True):
        if dolar is None:
            dolar = st.number_input("Dólar (R$ por US$)", min_value=0.0, value=0.0, step=0.01, key="manual_dolar")
            dolar_fonte = "manual"
        for ativo in sem_preco:
            precos_manuais[ativo] = st.number_input(
                f"Preço de {ativo}", min_value=0.0, value=0.0, step=0.01, key=f"manual_{ativo}")

if not dolar:
    st.error("Sem a cotação do dólar não dá para converter os ativos em dólar para R$.")
    st.stop()

# Monta a tabela de preços (será usada no próximo passo, para calcular os valores).
linhas = []
for _, linha in carteira.iterrows():
    ativo = linha["ativo"]
    if ativo not in consultas:  # Caixa
        preco, data, fonte = 1.0, None, "caixa (valor 1)"
    else:
        preco, data = consultas[ativo]
        fonte = "Yahoo"
        if preco is None:
            preco = precos_manuais.get(ativo) or None  # 0 vira "faltando"
            fonte = "manual" if preco else "FALTANDO"
    linhas.append({
        "ativo": ativo,
        "moeda": linha["moeda"],
        "preco": round(preco, 4) if preco else None,
        "data_do_preco": data.strftime("%d/%m/%Y") if data else "-",
        "fonte": fonte,
    })
tabela_precos = pd.DataFrame(linhas)

st.metric("Dólar (R$ por US$)", f"{dolar:.4f}",
          help=f"Fonte: {dolar_fonte}" + (f", preço de {data_dolar.strftime('%d/%m/%Y')}" if data_dolar else ""))
st.dataframe(tabela_precos, hide_index=True)

# Avisos honestos sobre a qualidade dos preços.
if (tabela_precos["fonte"] == "FALTANDO").any():
    faltando = ", ".join(tabela_precos.loc[tabela_precos["fonte"] == "FALTANDO", "ativo"])
    st.warning(f"Ainda sem preço: {faltando}. Os cálculos precisam de todos os preços.")

datas = [d for _, d in consultas.values() if d is not None]
if datas and (date.today() - min(datas)).days > DIAS_PARA_AVISAR:
    st.warning(f"Há preços com mais de {DIAS_PARA_AVISAR} dias (o mais antigo é de {min(datas).strftime('%d/%m/%Y')}).")

st.caption("Os preços vêm do Yahoo Finance pela biblioteca yfinance (gratuita e não oficial) e podem divergir "
           "da cotação da corretora ou ter atraso.")


# ---------------------------------------------------------------------------
# Item 5: formulários de movimentação (compra, venda, aporte e retirada de caixa)
# ---------------------------------------------------------------------------
def registrar_caixa(carteira, tipo, valor):
    """Soma (aporte) ou subtrai (retirada) dinheiro da linha Caixa. Devolve uma mensagem de erro, ou None se deu certo."""
    linha_caixa = carteira["ativo"] == "Caixa"
    if not linha_caixa.any():
        return "A carteira não tem uma linha chamada Caixa."
    if valor <= 0:
        return "Digite um valor maior que zero."
    caixa_atual = float(carteira.loc[linha_caixa, "quantidade"].iloc[0])
    if tipo == "Retirada de caixa" and valor > caixa_atual:
        return f"Retirada maior que o caixa disponível ({formata_rs(caixa_atual)})."
    sinal = 1 if tipo == "Aporte de caixa" else -1
    carteira.loc[linha_caixa, "quantidade"] = round(caixa_atual + sinal * valor, 2)
    return None


def registrar_negociacao(carteira, ativo, operacao, modo, numero, preco, dolar_do_dia):
    """Compra ou venda de um ativo. Muda a quantidade do ativo e ajusta o Caixa sozinho.
    modo = "Quantidade" (numero é a quantidade) ou "Valor (R$)" (numero é o valor em R$; a quantidade é calculada).
    Devolve (mensagem_de_erro, detalhes). Se deu certo, a mensagem é None."""
    linha_ativo = carteira["ativo"] == ativo
    linha_caixa = carteira["ativo"] == "Caixa"
    if not linha_caixa.any():
        return "A carteira não tem uma linha chamada Caixa.", None
    if ativo == "Caixa" or not linha_ativo.any():
        return "Escolha um ativo da carteira (para mexer no caixa use aporte ou retirada).", None
    if numero <= 0:
        return "Digite um número maior que zero.", None

    moeda = carteira.loc[linha_ativo, "moeda"].iloc[0]
    preco_em_rs = preco * (dolar_do_dia if moeda == "USD" else 1.0)  # preço de 1 unidade, já em R$

    # Se a pessoa informou o valor em R$, a quantidade é valor ÷ preço.
    quantidade = numero if modo == "Quantidade" else numero / preco_em_rs
    quantidade = round(quantidade, 6)
    if quantidade <= 0:
        return "Valor pequeno demais: a quantidade calculada ficou zero.", None

    qtd_atual = float(carteira.loc[linha_ativo, "quantidade"].iloc[0])
    caixa_atual = float(carteira.loc[linha_caixa, "quantidade"].iloc[0])

    if operacao == "Venda":
        if quantidade > qtd_atual + 1e-6:  # pequena folga para sobras de arredondamento
            return f"Você tem só {qtd_atual:g} de {ativo}; não dá para vender {quantidade:g}.", None
        quantidade = min(quantidade, qtd_atual)
        valor_rs = round(quantidade * preco_em_rs, 2)
        nova_qtd, novo_caixa = qtd_atual - quantidade, caixa_atual + valor_rs
    else:  # Compra
        valor_rs = round(quantidade * preco_em_rs, 2)
        if valor_rs > caixa_atual + 0.005:
            return (f"Caixa insuficiente: a compra custa {formata_rs(valor_rs)} e o caixa tem "
                    f"{formata_rs(caixa_atual)}. Registre um aporte ou uma venda antes."), None
        nova_qtd, novo_caixa = qtd_atual + quantidade, caixa_atual - valor_rs

    carteira.loc[linha_ativo, "quantidade"] = round(nova_qtd, 6)
    carteira.loc[linha_caixa, "quantidade"] = round(novo_caixa, 2)
    return None, {"quantidade": quantidade, "preco": preco, "valor_rs": valor_rs}


def ler_numero(texto):
    """Lê um número digitado em texto. Aceita 100, 0.5, 0,5 e 1.234,56 (formato brasileiro).
    Regra: se tem vírgula, a vírgula é o decimal e os pontos são separador de milhar;
    se não tem vírgula, o ponto é o decimal (então 1.000 vale 1, e 1000 ou 1.000,00 valem mil).
    Devolve o número, ou None se estiver vazio ou não der para entender."""
    texto = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = float(texto)
    except ValueError:
        return None
    if numero != numero or numero in (float("inf"), float("-inf")):  # descarta "nan" e "inf"
        return None
    return numero


def mensagem_numero_invalido(texto):
    """Mensagem de erro para um campo de número vazio ou ilegível."""
    if not (texto or "").strip():
        return "Digite um número maior que zero."
    return f"Não entendi o número '{texto}'. Use só dígitos, com vírgula ou ponto para os decimais (ex.: 0,5)."


def agora():
    """Data e hora de Brasília, para o registro das movimentações."""
    return pd.Timestamp.now(tz="America/Sao_Paulo").strftime("%d/%m/%Y %H:%M")


with st.expander("Registrar movimentação", expanded=False):
    # Mensagem de sucesso da última movimentação (guardada porque a tela é recarregada depois de salvar).
    if st.session_state.get("mensagem"):
        st.success(st.session_state.pop("mensagem"))

    # --- Compra e venda ---
    with st.form("form_negociacao", clear_on_submit=True):
        st.markdown("**Compra ou venda de um ativo** (o caixa se ajusta sozinho, ao preço mostrado na tabela de preços)")
        ativo_escolhido = st.selectbox("Ativo", [a for a in carteira["ativo"] if a != "Caixa"])
        operacao = st.radio("Operação", ["Compra", "Venda"], horizontal=True)
        modo = st.radio("Informar por", ["Quantidade", "Valor (R$)"], horizontal=True)
        # Campo de texto (e não de número) para aceitar vírgula e ponto; quem lê o número é a função ler_numero.
        numero = st.text_input("Quantidade ou valor em R$ (conforme a opção acima)",
                               placeholder="Ex.: 10, 0,5 ou 1.250,50",
                               help="Pode usar vírgula ou ponto nos decimais. Sem vírgula, o ponto vale como decimal "
                                    "(1.000 é um; para mil, escreva 1000).")
        enviado_negociacao = st.form_submit_button("Registrar compra/venda")

    if enviado_negociacao:
        numero_lido = ler_numero(numero)
        linha_preco = tabela_precos[tabela_precos["ativo"] == ativo_escolhido].iloc[0]
        if numero_lido is None:
            st.error(mensagem_numero_invalido(numero))
        elif linha_preco["fonte"] == "FALTANDO":
            st.error(f"Sem preço para {ativo_escolhido}. Digite o preço manualmente na seção de preços.")
        else:
            erro_negociacao, detalhes = registrar_negociacao(
                carteira, ativo_escolhido, operacao, modo, numero_lido, linha_preco["preco"], dolar)
            if erro_negociacao:
                st.error(erro_negociacao)
            else:
                st.session_state["movimentacoes"].append(
                    {"quando": agora(), "tipo": operacao, "ativo": ativo_escolhido,
                     "quantidade": detalhes["quantidade"], "preco": detalhes["preco"],
                     "valor_rs": detalhes["valor_rs"]})
                st.session_state["mensagem"] = (
                    f"{operacao} de {detalhes['quantidade']:g} {ativo_escolhido} registrada "
                    f"({formata_rs(detalhes['valor_rs'])}).")
                st.rerun()  # recarrega a tela para a carteira e o painel já mostrarem a mudança

    # --- Aporte e retirada de caixa ---
    with st.form("form_caixa", clear_on_submit=True):
        st.markdown("**Dinheiro que entra ou sai da carteira**")
        tipo = st.radio("Tipo", ["Aporte de caixa", "Retirada de caixa"], horizontal=True)
        valor = st.text_input("Valor (R$)", placeholder="Ex.: 500 ou 1.250,50",
                              help="Pode usar vírgula ou ponto nos decimais. Sem vírgula, o ponto vale como decimal "
                                   "(1.000 é um; para mil, escreva 1000).")
        enviado_caixa = st.form_submit_button("Registrar caixa")

    if enviado_caixa:
        valor_lido = ler_numero(valor)
        erro_caixa = mensagem_numero_invalido(valor) if valor_lido is None else registrar_caixa(carteira, tipo, valor_lido)
        if erro_caixa:
            st.error(erro_caixa)
        else:
            st.session_state["movimentacoes"].append(
                {"quando": agora(), "tipo": tipo, "ativo": "Caixa", "valor_rs": valor_lido})
            st.session_state["mensagem"] = f"{tipo} de {formata_rs(valor_lido)} registrado."
            st.rerun()

    if st.session_state["movimentacoes"]:
        st.markdown("**Movimentações desta sessão**")
        historico = pd.DataFrame(st.session_state["movimentacoes"]).rename(columns={
            "quando": "Quando", "tipo": "Tipo", "ativo": "Ativo", "quantidade": "Quantidade",
            "preco": "Preço (moeda do ativo)", "valor_rs": "Valor (R$)"})
        st.dataframe(  # aporte e retirada não têm quantidade nem preço: aparecem como "-"
            historico.style.format({"Quantidade": formata_quantidade, "Preço (moeda do ativo)": formata_preco,
                                    "Valor (R$)": formata_rs}, na_rep="-"),
            hide_index=True)


# ---------------------------------------------------------------------------
# Item 3: valores em R$ e diferença para a meta
# ---------------------------------------------------------------------------
if (tabela_precos["fonte"] == "FALTANDO").any():
    st.stop()  # o aviso já foi mostrado acima; sem todos os preços não dá para calcular

try:
    por_ativo, por_classe, patrimonio = calcular(carteira, metas, tabela_precos, dolar)
except Exception as erro:
    st.error(f"Não consegui calcular os valores: {erro}")
    st.stop()

st.divider()
st.subheader("Painel: onde estou em relação à meta")
st.metric("Patrimônio total", formata_rs(patrimonio))
st.caption("Diferença = valor atual menos a meta. "
           "Vermelho: abaixo da meta (falta comprar). Azul: acima da meta. Verde: na meta (diferença menor que R$ 1).")

# --- Cartões por classe (3 por linha) ---
st.markdown("**Por classe**")
por_classe["situacao"] = por_classe["diferenca_rs"].apply(situacao)
linhas_de_cartoes = [por_classe.iloc[i:i + 3] for i in range(0, len(por_classe), 3)]
for grupo in linhas_de_cartoes:
    colunas = st.columns(3)
    for coluna, (_, classe) in zip(colunas, grupo.iterrows()):
        with coluna:
            st.metric(
                label=f"{classe['classe']} - {formata_pct(classe['pct_atual'])} (meta {formata_pct(classe['meta_pct'])})",
                value=formata_rs(classe["valor_rs"]),
                delta=f"{formata_rs(classe['diferenca_rs'])} vs meta",
                delta_color="off" if classe["situacao"] == "Na meta" else "normal",
            )

# --- Tabela por classe, colorida ---
tabela_classe = por_classe.rename(columns={
    "classe": "Classe", "meta_pct": "Meta (%)", "valor_rs": "Valor (R$)", "pct_atual": "Atual (%)",
    "meta_rs": "Meta (R$)", "diferenca_rs": "Diferença (R$)", "situacao": "Situação"})
tabela_classe = tabela_classe[["Classe", "Valor (R$)", "Atual (%)", "Meta (%)", "Meta (R$)", "Diferença (R$)", "Situação"]]
st.dataframe(
    tabela_colorida(tabela_classe, ["Valor (R$)", "Meta (R$)", "Diferença (R$)"], ["Atual (%)", "Meta (%)"]),
    hide_index=True)

# --- Tabela por ativo, colorida ---
st.markdown("**Por ativo**")
por_ativo["situacao"] = por_ativo["diferenca_rs"].apply(situacao)
tabela_ativo = por_ativo.rename(columns={
    "ativo": "Ativo", "classe": "Classe", "quantidade": "Quantidade", "preco": "Preço",
    "moeda": "Moeda do preço", "valor_rs": "Valor (R$)", "pct_atual": "Atual (%)",
    "meta_pct_total": "Meta (%)", "meta_rs": "Meta (R$)", "diferenca_rs": "Diferença (R$)",
    "situacao": "Situação"})
st.dataframe(
    tabela_colorida(tabela_ativo, ["Valor (R$)", "Meta (R$)", "Diferença (R$)"], ["Atual (%)", "Meta (%)"]),
    hide_index=True)
