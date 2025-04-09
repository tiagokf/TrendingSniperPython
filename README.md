# RoboCriptoCL - Bot de Trading Automatizado para Binance

## 📋 Descrição

RoboCriptoCL é um bot de trading automatizado projetado para operar na exchange Binance. O bot utiliza análise técnica e diversas estratégias configuráveis para identificar oportunidades de trading em criptomoedas. Ele inclui gerenciamento de risco adaptativo, trailing stops, e um dashboard web em tempo real para monitoramento.

### 🌟 Características Principais

- **Múltiplas Estratégias**: Suporte para diferentes estratégias de trading (Scalping, Trend Sniper)
- **Dashboard Interativo**: Interface web com Dash para monitoramento de trades e performance
- **Gerenciamento de Risco Adaptativo**: Ajusta automaticamente parâmetros com base na volatilidade do mercado
- **Trailing Stop**: Sistema de trailing stop para maximizar lucros em mercados favoráveis
- **Seleção Inteligente de Moedas**: Filtragem de pares com base em volume, volatilidade e tendência
- **Tratamento de Rate Limits**: Respeita os limites de API da Binance
- **Cache Eficiente**: Sistema de cache para otimizar chamadas à API

## 🔧 Instalação

### Pré-requisitos

- Python 3.8 ou superior
- Conta na Binance com API Key/Secret

### Instalação via pip

1. Clone o repositório:
```bash
git clone https://github.com/seu-usuario/robocriptocl.git
cd robocriptocl
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Configure as variáveis de ambiente (veja a seção "Configuração")

4. Execute o bot:
```bash
python run.py
```

## ⚙️ Configuração

### Arquivo .env

Copie o arquivo `.env.example` para `.env` e preencha com suas configurações:

```bash
cp .env.example .env
```

### Parâmetros principais:

#### API Keys
```
BINANCE_API_KEY=sua_api_key_aqui
BINANCE_API_SECRET=sua_api_secret_aqui
```

#### Parâmetros de Trading
```
QUOTE_ASSET=USDT                # Moeda base para trading (USDT, BTC, etc)
MAX_ACTIVE_COINS=5              # Número máximo de moedas para operar simultaneamente
MIN_VOLUME_24H=10000000         # Volume mínimo em 24h (em USDT)
MIN_MARKET_CAP=100000000        # Market Cap mínimo (em USDT)
INCLUDE_COINS=BTC,ETH           # Moedas para incluir sempre (separadas por vírgula)
EXCLUDE_COINS=                  # Moedas para excluir (separadas por vírgula)
TRADING_AMOUNT_PERCENT=50       # Percentual do saldo disponível para usar em cada trade
MAX_ORDERS_PER_COIN=2           # Máximo de ordens simultâneas por moeda
PROFIT_TARGET=0.5               # Alvo de lucro em percentual
STOP_LOSS=0.3                   # Stop loss em percentual
UPTREND_REQUIRED=true           # Exigir que a moeda esteja em tendência de alta
```

#### Parâmetros de Estratégia Scalping
```
RSI_PERIOD=14
RSI_OVERBOUGHT=70
RSI_OVERSOLD=30
EMA_SHORT=9
EMA_MEDIUM=21
EMA_LONG=50
BB_PERIOD=20
BB_STD_DEV=2
```

#### Configurações avançadas
```
HIGH_VOL_PROFIT_TARGET=1.8      # Alvo de lucro para moedas voláteis (%)
HIGH_VOL_STOP_LOSS=1.5          # Stop loss para moedas voláteis (%)
HIGH_VOLATILITY_THRESHOLD=2.0   # Limiar para considerar alta volatilidade
TRAILING_STOP=true              # Ativar trailing stop
TRAILING_STOP_ACTIVATION=0.40   # Ativar trailing quando atingir % do target
TRAILING_STOP_DISTANCE=0.25     # Distância do trailing stop (%)
```

#### Configurações do Dashboard
```
DASHBOARD_PORT=8050             # Porta para o dashboard web
REFRESH_INTERVAL=5              # Intervalo de atualização em segundos
COIN_SELECTION_INTERVAL=60      # Intervalo para reavaliação de moedas (minutos)
```

#### Configurações de Log
```
LOG_LEVEL=INFO                  # Nível de log (INFO, DEBUG, WARNING, ERROR)
```

## 💼 Estratégias Disponíveis

### 1. Scalping Strategy

Estratégia para operações de curta duração, buscando pequenas oscilações de preço. Utiliza RSI, EMAs e Bollinger Bands.

#### Parâmetros relevantes:
- `RSI_PERIOD`, `RSI_OVERBOUGHT`, `RSI_OVERSOLD`
- `EMA_SHORT`, `EMA_MEDIUM`, `EMA_LONG`
- `BB_PERIOD`, `BB_STD_DEV`

### 2. Trend Sniper Strategy

Estratégia focada em capturar movimentos de tendência de média duração. Utiliza EMAs e RSI para identificar tendências.

#### Parâmetros relevantes:
- `EMA_PERIODS` (padrão [9, 21, 50])
- `RSI_PERIOD`
- `VOLUME_PERIOD`

## 🚀 Uso

### Iniciando o Bot

Execute o arquivo principal:

```bash
python run.py
```

### Acessando o Dashboard

Após iniciar o bot, acesse o dashboard no navegador:

```
http://localhost:8050
```
(ou a porta definida em `DASHBOARD_PORT`)

### Controles do Dashboard

- **Start Bot**: Inicia as operações automatizadas
- **Stop Bot**: Pausa as operações (mantém posições abertas)
- **Sell All**: Vende todas as posições abertas

### Monitoramento

O dashboard apresenta:

1. **Bot Status & Wallet**: Status do bot e saldos da carteira
2. **Trading Performance**: Desempenho geral (lucro/perda, win rate)
3. **Open Positions**: Posições atualmente abertas
4. **Active Coins**: Moedas sendo monitoradas e seus status

## 🎛️ Ajustes Finos

### Otimização de Parâmetros

Para melhorar o desempenho do bot, considere ajustar:

1. **Profit Target e Stop Loss**:
   - Para mercados em alta: Aumente o profit target e o stop loss
   - Para mercados laterais: Reduza o profit target e mantenha stop loss mais próximo

2. **Parâmetros de Trailing Stop**:
   - `TRAILING_STOP_ACTIVATION`: Mais alto (0.6-0.8) em mercados voláteis
   - `TRAILING_STOP_DISTANCE`: Mais próximo (0.1-0.2%) em mercados estáveis, mais distante (0.3-0.5%) em mercados voláteis

3. **Seleção de Moedas**:
   - Aumente `MIN_VOLUME_24H` para moedas mais líquidas (menor slippage)
   - Ative `UPTREND_REQUIRED=true` em mercados de alta
   - Use `INCLUDE_COINS` para forçar trading em moedas específicas

### Ajuste para Diferentes Condições de Mercado

#### Mercado em Alta (Bull Market)
```
PROFIT_TARGET=1.0
STOP_LOSS=0.5
UPTREND_REQUIRED=true
TRAILING_STOP=true
TRAILING_STOP_ACTIVATION=0.50
```

#### Mercado Lateral (Sideways)
```
PROFIT_TARGET=0.5
STOP_LOSS=0.3
UPTREND_REQUIRED=false
MAX_ACTIVE_COINS=3
```

#### Mercado em Queda (Bear Market)
```
# Recomendado: desativar o bot ou operar apenas BTC/ETH
INCLUDE_COINS=BTC,ETH
EXCLUDE_COINS=
MAX_ACTIVE_COINS=2
TRADING_AMOUNT_PERCENT=30
PROFIT_TARGET=0.4
STOP_LOSS=0.2
```

## 📈 Logs e Análise de Desempenho

### Arquivos de Log

- **robocriptocl.log**: Log principal do sistema
- **performance.log**: Dados de performance ao longo do tempo
- **trades.log**: Registro de todas as operações realizadas

### Análise de Desempenho

Para analisar o desempenho do bot:

1. Monitore o win rate no dashboard
2. Analise os logs de trades para identificar padrões de sucesso/falha
3. Verifique a correlação entre condições de mercado e performance

## 🛠️ Solução de Problemas

### Problemas Comuns

1. **Erro de API Key Invalid**: Verifique se suas chaves de API estão configuradas corretamente e têm permissões de trading

2. **Insufficient Balance**: Certifique-se de ter saldo suficiente para o tamanho de ordem mínimo exigido pela Binance

3. **MIN_NOTIONAL Error**: Aumente o valor de `TRADING_AMOUNT_PERCENT` ou reduza `MAX_ACTIVE_COINS`

4. **Rate Limit Exceeded**: O bot automaticamente gerencia os rate limits, mas para alta frequência de trading, considere aumentar `REFRESH_INTERVAL`

### Logs de Depuração

Para logs mais detalhados, altere o nível de log:

```
LOG_LEVEL=DEBUG
```

## ⚠️ Considerações de Segurança

- **Nunca compartilhe suas chaves de API**
- Recomenda-se criar chaves de API com permissões restritas (leitura e trading, sem permissão de saque)
- Verifique regularmente os saldos na Binance para garantir consistência com o relatado pelo bot
- Inicie com valores pequenos até confirmar que tudo está funcionando conforme esperado

## 📜 Licença

Este projeto está licenciado sob a Licença MIT - veja o arquivo LICENSE.md para detalhes.

## 📞 Suporte e Contato

Para suporte, entre em contato: tiago@tiremoto.com.br

---

⚠️ **Aviso de Risco**: Trading de criptomoedas envolve riscos significativos. Este bot é fornecido apenas para fins educacionais e de experimentação. Não é um conselho financeiro. Use por sua conta e risco.
