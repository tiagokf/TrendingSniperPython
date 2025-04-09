import logging

class TrendSniperStrategy:
    def __init__(self, config):
        self.logger = logging.getLogger('RoboCriptoCL.TrendSniperStrategy')
        self.config = config

        # Parâmetros de análise técnica
        self.ema_periods = getattr(config, 'ema_periods', [9, 21, 50])
        self.rsi_period = config.rsi_period or 14
        self.volume_period = getattr(config, 'volume_period', 3)

        self.logger.info(
            f"TrendSniper initialized with EMAs{tuple(self.ema_periods)} and RSI({self.rsi_period})"
        )

    def analyze(self, symbol_data):
        """
        Análise técnica para determinar se há sinal de compra.
        """
        candles = symbol_data.get("candles", [])
        if len(candles) < max(self.ema_periods + [self.rsi_period]):
            return None  # Não há dados suficientes

        closes = [c["close"] for c in candles]
        volumes = [c["volume"] for c in candles]

        # Calcular EMAs
        def ema(values, period):
            multiplier = 2 / (period + 1)
            ema_values = [sum(values[:period]) / period]
            for price in values[period:]:
                ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
            return ema_values

        ema_short = ema(closes, self.ema_periods[0])[-1]
        ema_medium = ema(closes, self.ema_periods[1])[-1]
        ema_long = ema(closes, self.ema_periods[2])[-1]

        # Calcular RSI
        def calculate_rsi(data, period):
            gains = []
            losses = []
            for i in range(1, period + 1):
                change = data[-(i + 1)] - data[-(i + 2)]
                if change > 0:
                    gains.append(change)
                else:
                    losses.append(abs(change))
            avg_gain = sum(gains) / period if gains else 0.0001
            avg_loss = sum(losses) / period if losses else 0.0001
            rs = avg_gain / avg_loss
            return 100 - (100 / (1 + rs))

        rsi = calculate_rsi(closes, self.rsi_period)

        # Verificar tendência de alta
        if ema_short > ema_medium > ema_long and rsi > 55:
            self.logger.info(f"Uptrend detected: EMA({self.ema_periods}) and RSI({self.rsi_period}) = {rsi:.2f}")
            return {
                "signal": "buy",
                "entry_price": closes[-1],
                "rsi": rsi,
                "ema_short": ema_short,
                "ema_medium": ema_medium,
                "ema_long": ema_long,
            }

        return None

    def detect_uptrend(self, symbol_data):
        """
        Detecta se o ativo está em tendência de alta com base nas EMAs.
        """
        candles = symbol_data.get("candles", [])
        if len(candles) < max(self.ema_periods + [self.rsi_period]):
            return False

        closes = [c["close"] for c in candles]

        # Calcular EMAs
        def ema(values, period):
            multiplier = 2 / (period + 1)
            ema_values = [sum(values[:period]) / period]
            for price in values[period:]:
                ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
            return ema_values

        ema_short = ema(closes, self.ema_periods[0])[-1]
        ema_medium = ema(closes, self.ema_periods[1])[-1]
        ema_long = ema(closes, self.ema_periods[2])[-1]

        # Lógica simples de tendência de alta
        return ema_short > ema_medium > ema_long
