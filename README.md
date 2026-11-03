# 🛒 Caçador de Preços — Web Scraper & Discord Bot

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Async-2EAD33?logo=playwright&logoColor=white)
![Discord.py](https://img.shields.io/badge/Discord.py-2.4%2B-5865F2?logo=discord&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?logo=pydantic&logoColor=white)

Pesquisador automatizado de preços e reputação de produtos que consulta simultaneamente **Amazon**, **Mercado Livre**, **Americanas** e **Shopee** utilizando **Playwright**, ranqueia as ofertas mais baratas e confiáveis através de **Média Bayesiana** e disponibiliza os resultados via **Terminal (CLI)**, **Webhook** ou **Bot Interativo no Discord (`/preco`)**.

---

## ✨ Funcionalidades

- **Busca Simultânea Assíncrona:** Varre as 4 lojas em paralelo usando contextos isolados do Playwright (`asyncio`).
- **Ranking Inteligente (Preço + Confiabilidade):** Aplica a fórmula da **Média Bayesiana Ponderada** sobre a nota em estrelas e o volume de avaliações para evitar produtos suspeitos com poucas avaliações.
- **Filtro de Relevância:** Descarta automaticamente acessórios ou itens não relacionados que distorceriam o menor preço.
- **Links Limpos e Diretos:** Remove parâmetros extensos de rastreamento, gerando URLs curtas e prontas para acesso.
- **Integração Completa com Discord:**
  - **Slash Command `/preco` e comando `!preco`:** Pesquise direto pelo chat do Discord (no PC ou celular).
  - **Notificação `@usuario`:** O bot marca automaticamente quem solicitou a busca assim que o scraping termina.
  - **Webhook:** Envie relatórios do terminal diretamente para um canal de ofertas usando `--discord`.

---

## 🧠 Como Funciona o Cálculo de Confiabilidade

Um anúncio com **1 avaliação nota 5.0** não é mais confiável que um produto com **1.500 avaliações nota 4.8**. Para corrigir essa distorção, o módulo [`scorer.py`](price_tracker/scorer.py) calcula a **Média Bayesiana**:

$$WR = \left(\frac{v}{v + m}\right) \cdot R + \left(\frac{m}{v + m}\right) \cdot C$$

- $WR$: Índice de confiabilidade ponderado (`0.0` a `5.0`).
- $v$: Total de avaliações do produto.
- $m$: Mínimo de avaliações exigido para peso integral (padrão: `20`).
- $R$: Nota média do produto (`0.0` a `5.0`).
- $C$: Nota média de referência do mercado (`3.5`).

O sistema filtra as ofertas confiáveis ($v \ge 5$ e $WR \ge 3.8$) e seleciona as **3 opções mais baratas**.

---

## 📂 Estrutura do Projeto

```text
├── price_tracker/
│   ├── adapters/           # Adaptadores independentes por loja (Strategy Pattern)
│   │   ├── base.py         # Classe base e utilitários de navegação humana
│   │   ├── amazon.py       # Extrator Amazon Brasil
│   │   ├── americanas.py   # Extrator Americanas (GraphQL + JSON-LD + DOM)
│   │   ├── mercadolivre.py # Extrator Mercado Livre
│   │   └── shopee.py       # Extrator Shopee (API v4 Interception + DOM)
│   ├── browser.py          # Gerenciador Playwright, Stealth e Perfis Persistentes
│   ├── engine.py           # Orquestrador assíncrono multiloja
│   ├── models.py           # Esquemas de dados Pydantic (ProductOffer, StoreResult)
│   ├── scorer.py           # Média Bayesiana, filtro de relevância e Top 3
│   ├── utils.py            # Limpeza de preços BRL, notas, contagens e URLs
│   ├── discord_notifier.py # Construtor de Embeds e envio via Webhook
│   ├── discord_bot.py      # Bot interativo do Discord (/preco + @usuario)
│   └── cli.py              # Interface de linha de comando (CLI)
├── tests/
│   └── test_price_tracker.py
├── .env.example            # Modelo de variáveis de ambiente
├── iniciar_bot.bat         # Atalho para ligar o Bot no Windows com 2 cliques
└── requirements.txt
```

---

## 🚀 Instalação e Configuração

### 1. Clonar o repositório e criar o ambiente virtual

```powershell
git clone https://github.com/lupajr/botScrapping.git
cd botScrapping

python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Instalar as dependências e o navegador do Playwright

```powershell
pip install -r requirements.txt
playwright install chromium
```

### 3. Configurar as variáveis de ambiente (`.env`)

Copie o arquivo `.env.example` para `.env` e preencha com os dados do seu canal/bot do Discord:

```powershell
copy .env.example .env
```

> ⚠️ **Segurança:** O arquivo `.env` e a pasta `.browser_profiles/` já estão listados no [`.gitignore`](.gitignore) para que seus tokens e sessões nunca vazem no GitHub.

---

## 💻 Uso pelo Terminal (CLI)

```powershell
# Busca padrão nas 4 lojas:
python -m price_tracker "fone bluetooth jbl"

# Busca abrindo os 3 links vencedores no navegador e enviando para o Discord:
python -m price_tracker "fone bluetooth jbl" --abrir --discord

# Busca filtrando lojas específicas e definindo preço mínimo:
python -m price_tracker "iphone 15 128gb" --lojas amazon americanas --preco-min 3500

# Exportar resultado completo em JSON:
python -m price_tracker "monitor 24 144hz" --json resultado.json
```

### Autenticação única para Shopee / Mercado Livre
Quando acessadas sem sessão, a Shopee e o Mercado Livre podem solicitar login/verificação. Execute uma única vez para salvar os cookies localmente em `.browser_profiles/`:

```powershell
python -m price_tracker --login shopee
python -m price_tracker --login mercadolivre
```

---

## 🤖 Como Ligar e Desligar o Bot do Discord

### Para LIGAR o Bot:
- **Pelo Windows Explorer:** Dê **2 cliques** no arquivo [`iniciar_bot.bat`](iniciar_bot.bat).
- **Pelo Terminal PowerShell:**
  ```powershell
  .\.venv\Scripts\python.exe -m price_tracker.discord_bot
  ```

### Para DESLIGAR o Bot:
- Na janela do terminal onde o bot está rodando, pressione **`Ctrl + C`** (ou simplesmente feche a janela).

### Comandos dentro do Discord:
- `/preco produto: fone bluetooth jbl` *(Slash Command oficial)*
- `!preco fone bluetooth jbl` *(Comando por texto)*

O bot iniciará a varredura nas lojas e enviará uma notificação marcando **`@usuario`** assim que o Top 3 estiver pronto.

---

## 🧪 Testes Automatizados

Para rodar a suíte de testes unitários (parsers de cada loja, limpeza de preços e cálculo bayesiano):

```powershell
python -m unittest discover -s tests -v
```
