import os
from dotenv import load_dotenv
import logging


# Implementação própria do strtobool para substituir distutils
def strtobool(val):
    """Converte uma string para um booleano."""
    val = str(val).lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    elif val in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    else:
        raise ValueError(f"valor booleano inválido: {val}")

class Config:
    def __init__(self):
        # Load .env file
        load_dotenv()

        # Load environment variables
        self.strategy = os.getenv('STRATEGY', 'scalping')

        self.volume_period = int(os.getenv('VOLUME_PERIOD', '3'))

        # Setup logging
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self._setup_logging()
        
        # API credentials
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        
        # Trading parameters
        self.quote_asset = os.getenv('QUOTE_ASSET', 'USDT')
        self.max_active_coins = int(os.getenv('MAX_ACTIVE_COINS', '5'))
        self.min_volume_24h = float(os.getenv('MIN_VOLUME_24H', '10000000'))
        self.min_market_cap = float(os.getenv('MIN_MARKET_CAP', '100000000'))
        
        # Coin filtering
        include_coins = os.getenv('INCLUDE_COINS', 'BTC,ETH')
        self.include_coins = [coin.strip() for coin in include_coins.split(',')] if include_coins else []
        
        exclude_coins = os.getenv('EXCLUDE_COINS', '')
        self.exclude_coins = [coin.strip() for coin in exclude_coins.split(',')] if exclude_coins else []
        
        # Risk management - reduzido para melhor controle de risco
        self.trading_amount_percent = float(os.getenv('TRADING_AMOUNT_PERCENT', '1')) / 100
        self.max_orders_per_coin = int(os.getenv('MAX_ORDERS_PER_COIN', '3'))  # Aumentado para permitir mais trades
        self.min_balance_required = float(os.getenv('MIN_BALANCE_REQUIRED', '10.0'))  # Saldo mínimo para operar
        self.fee_percentage = float(os.getenv('FEE_PERCENTAGE', '0.1'))  # Taxa da exchange (0.1% por padrão na Binance)
        
        # Profit targets e stop loss adaptados para maior volatilidade - aumentados para dar mais espaço ao mercado
        self.profit_target = float(os.getenv('PROFIT_TARGET', '1.2')) / 100  # Aumentado de 0.8% para 1.2%
        self.stop_loss = float(os.getenv('STOP_LOSS', '1.0')) / 100  # Aumentado de 0.5% para 1.0%
        
        # Profit target e stop loss para moedas de alta volatilidade - ajustados para melhor performance
        self.high_vol_profit_target = float(os.getenv('HIGH_VOL_PROFIT_TARGET', '1.8')) / 100  # Aumentado de 1.2% para 1.8%
        self.high_vol_stop_loss = float(os.getenv('HIGH_VOL_STOP_LOSS', '1.5')) / 100  # Aumentado de 0.7% para 1.5%
        
        # Threshold de volatilidade para classificar moedas
        self.high_volatility_threshold = float(os.getenv('HIGH_VOLATILITY_THRESHOLD', '2.0'))  # Percentual de volatilidade média
        
        # Trailing stop loss configuration - modificado para ser mais eficiente
        self.trailing_stop = bool(strtobool(os.getenv('TRAILING_STOP', 'true')))
        self.trailing_stop_activation = float(os.getenv('TRAILING_STOP_ACTIVATION', '0.40'))  # Aumentado de 0.20 para 0.40 (40% do target)
        self.trailing_stop_distance = float(os.getenv('TRAILING_STOP_DISTANCE', '0.25')) / 100  # Aumentado de 0.12% para 0.25%
        
        self.uptrend_required = bool(strtobool(os.getenv('UPTREND_REQUIRED', 'true')))
        
        # Strategy parameters
        self.rsi_period = int(os.getenv('RSI_PERIOD', '14'))
        self.rsi_overbought = int(os.getenv('RSI_OVERBOUGHT', '70'))
        self.rsi_oversold = int(os.getenv('RSI_OVERSOLD', '30'))
        self.ema_short = int(os.getenv('EMA_SHORT', '9'))
        self.ema_medium = int(os.getenv('EMA_MEDIUM', '21'))
        self.ema_long = int(os.getenv('EMA_LONG', '50'))
        self.bb_period = int(os.getenv('BB_PERIOD', '20'))
        self.bb_std_dev = int(os.getenv('BB_STD_DEV', '2'))
        
        # Dashboard settings
        self.dashboard_port = int(os.getenv('DASHBOARD_PORT', '8050'))
        self.refresh_interval = int(os.getenv('REFRESH_INTERVAL', '5'))
        self.coin_selection_interval = int(os.getenv('COIN_SELECTION_INTERVAL', '60'))
        
        self.logger.info(f"Configuration loaded with {self.max_active_coins} max active coins")
        if self.include_coins:
            self.logger.info(f"Always included coins: {', '.join(self.include_coins)}")
        
        def get(self, attr, default=None):
            return getattr(self, attr, default)

    def _setup_logging(self):
        # Converter nível de log para valor numérico
        numeric_level = getattr(logging, self.log_level.upper(), None)
        if not isinstance(numeric_level, int):
            numeric_level = logging.INFO
        
        # Configurar handler para console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        console_handler.setFormatter(console_formatter)
        
        # Configurar handler para arquivo com criação do diretório
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'logs')
        log_file = os.path.join(log_dir, 'robocriptocl.log')
        
        # Criar diretório de logs se não existir
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(numeric_level)
        file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(file_formatter)
        
        # Configurar o logger específico para o bot
        self.logger = logging.getLogger('RoboCriptoCL')
        self.logger.setLevel(numeric_level)
        self.logger.handlers.clear()  # Limpar handlers existentes para evitar duplicatas
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
        
        self.logger.info(f"Logging configurado. Nível: {self.log_level}, arquivo de log: {log_file}")

    def get(self, attr, default=None):
        return getattr(self, attr, default)