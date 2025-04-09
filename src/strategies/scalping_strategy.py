import pandas as pd
import numpy as np
import logging
from datetime import datetime

class ScalpingStrategy:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger('RoboCriptoCL.ScalpingStrategy')
        
        # Strategy parameters
        self.rsi_period = config.rsi_period
        self.rsi_overbought = config.rsi_overbought
        self.rsi_oversold = config.rsi_oversold
        self.ema_short = config.ema_short
        self.ema_medium = config.ema_medium
        self.ema_long = config.ema_long
        self.bb_period = config.bb_period
        self.bb_std_dev = config.bb_std_dev
        
        self.logger.info(f"Scalping strategy initialized with RSI({self.rsi_period}), EMAs({self.ema_short},{self.ema_medium},{self.ema_long}), BB({self.bb_period},{self.bb_std_dev})")
    
    def calculate_indicators(self, df):
        """Calculate technical indicators for the strategy"""
        # Make a copy to avoid modifying the original
        data = df.copy()
        
        # Calculate RSI
        data['price_change'] = data['close'].diff()
        data['gain'] = data['price_change'].apply(lambda x: x if x > 0 else 0)
        data['loss'] = data['price_change'].apply(lambda x: abs(x) if x < 0 else 0)
        
        # First average gain and loss
        data['avg_gain'] = data['gain'].rolling(window=self.rsi_period).mean()
        data['avg_loss'] = data['loss'].rolling(window=self.rsi_period).mean()
        
        # Calculate RS and RSI
        data['rs'] = data['avg_gain'] / data['avg_loss']
        data['rsi'] = 100 - (100 / (1 + data['rs']))
        
        # Calculate EMAs
        data['ema_short'] = data['close'].ewm(span=self.ema_short, adjust=False).mean()
        data['ema_medium'] = data['close'].ewm(span=self.ema_medium, adjust=False).mean()
        data['ema_long'] = data['close'].ewm(span=self.ema_long, adjust=False).mean()
        
        # Calculate Bollinger Bands
        data['bb_middle'] = data['close'].rolling(window=self.bb_period).mean()
        data['bb_std'] = data['close'].rolling(window=self.bb_period).std()
        data['bb_upper'] = data['bb_middle'] + (data['bb_std'] * self.bb_std_dev)
        data['bb_lower'] = data['bb_middle'] - (data['bb_std'] * self.bb_std_dev)
        
        # Volatility (using standard deviation)
        data['volatility'] = data['close'].rolling(window=self.bb_period).std() / data['close'] * 100
        
        # Price momentum (rate of change)
        data['price_momentum'] = data['close'].pct_change(periods=5) * 100
        
        # Volume change
        data['volume_change'] = data['volume'].pct_change() * 100
        
        # MACD
        data['macd'] = data['close'].ewm(span=12, adjust=False).mean() - data['close'].ewm(span=26, adjust=False).mean()
        data['macd_signal'] = data['macd'].ewm(span=9, adjust=False).mean()
        data['macd_hist'] = data['macd'] - data['macd_signal']
        
        # Stochastic Oscillator
        data['lowest_low'] = data['low'].rolling(window=14).min()
        data['highest_high'] = data['high'].rolling(window=14).max()
        data['stoch_k'] = 100 * ((data['close'] - data['lowest_low']) / (data['highest_high'] - data['lowest_low']))
        data['stoch_d'] = data['stoch_k'].rolling(window=3).mean()
        
        return data
    
    def detect_uptrend(self, df):
        """Determine if the market is in an uptrend"""
        if len(df) < self.ema_long:
            return False
            
        data = self.calculate_indicators(df)
        
        # Get last row
        current = data.iloc[-1]
        
        # Check EMA alignment (short > medium > long indicates uptrend)
        ema_aligned = current['ema_short'] > current['ema_medium'] > current['ema_long']
        
        # Check price in relation to EMAs
        price_above_ema = current['close'] > current['ema_medium']
        
        # Check MACD histogram is positive
        macd_positive = current['macd_hist'] > 0
        
        # Combined conditions for uptrend
        uptrend = price_above_ema and (ema_aligned or macd_positive)
        
        return uptrend
    
    def generate_signals(self, df):
        """Generate buy/sell signals based on indicators with adaptive volatility settings"""
        # Calculate indicators
        data = self.calculate_indicators(df)
        
        # Initialize signals column
        data['signal'] = 0  # 0: no signal, 1: buy, -1: sell
        
        # The last row is the current candle
        if len(data) < max(self.rsi_period, self.ema_long, self.bb_period) + 5:
            self.logger.warning(f"Not enough data for reliable signals. Need at least {max(self.rsi_period, self.ema_long, self.bb_period) + 5} candles.")
            return data
        
        # Current values (last row)
        current = data.iloc[-1]
        previous = data.iloc[-2]
        
        # Determine volatility context
        # Calculate average volatility over the last 20 periods
        recent_volatility = data['volatility'].iloc[-20:].mean() if len(data) >= 20 else data['volatility'].mean()
        
        # Adaptive settings based on volatility
        # For higher volatility coins, we want to be more conservative with entries
        # and more aggressive with exits to capture quick profits
        is_high_volatility = recent_volatility > 2.0  # Threshold for high volatility
        
        # Ajustar níveis RSI para capturar pontos de entrada mais fortes
        rsi_oversold_adjusted = 25 if is_high_volatility else 30  # Valores mais baixos para compras mais seletivas
        rsi_overbought_adjusted = 70 if is_high_volatility else 75  # Adaptado para volatilidade
        
        # Adjust Bollinger Band thresholds based on volatility
        bb_lower_threshold = 1.01 if is_high_volatility else 1.005  # 1% vs 0.5%
        bb_upper_threshold = 0.99 if is_high_volatility else 0.995  # 1% vs 0.5%
        
        # Buy signal conditions
        buy_signal = False
        
        # Condition 1: RSI crosses above oversold level with adaptive threshold
        rsi_buy_signal = previous['rsi'] < rsi_oversold_adjusted and current['rsi'] >= rsi_oversold_adjusted
        
        # Condition 2: Price is near Bollinger lower band with adaptive threshold
        bb_buy_signal = current['close'] <= current['bb_lower'] * bb_lower_threshold
        
        # Condition 3: Short EMA crosses above Medium EMA (bullish momentum)
        ema_cross_buy = previous['ema_short'] <= previous['ema_medium'] and current['ema_short'] > current['ema_medium']
        
        # Condition 4: Price is above long-term EMA (overall uptrend)
        uptrend_condition = current['close'] > current['ema_long']
        
        # Condition 5: Increasing volume with adaptive threshold
        volume_threshold = 15 if is_high_volatility else 10  # 15% vs 10%
        volume_increasing = current['volume_change'] > volume_threshold
        
        # Condition 6: MACD histogram turns positive
        macd_buy_signal = previous['macd_hist'] < 0 and current['macd_hist'] > 0
        
        # Condition 7: Stochastic crosses above 20
        stoch_threshold = 25 if is_high_volatility else 20  # 25 vs 20
        stoch_buy_signal = previous['stoch_k'] < stoch_threshold and current['stoch_k'] >= stoch_threshold
        
        # Condition 8: Detecting volatility expansion - good for scalping entries
        # Volatility increased significantly but not extremely (which could be a risk)
        vol_expansion = (
            current['volatility'] > previous['volatility'] * 1.2 and  # 20% increase in volatility
            current['volatility'] < previous['volatility'] * 2.0      # But not more than 100% increase
        )
        
        # Combined buy signal - different combinations of signals
        buy_conditions = [rsi_buy_signal, bb_buy_signal, ema_cross_buy, macd_buy_signal, stoch_buy_signal, vol_expansion]
        
        # Para estratégia mais eficiente, reduzir número de condições necessárias
        min_conditions = 2 if is_high_volatility else 1
        buy_conditions_met = sum(buy_conditions) >= min_conditions
        
        # Simplificar critérios de confirmação
        additional_confirmation = uptrend_condition
        
        buy_signal = buy_conditions_met and additional_confirmation
        
        # Sell signal conditions (using profit target and stop loss managed by the client class)
        # Here we only implement additional sell signals for the strategy
        sell_signal = False
        
        # Condition 1: RSI crosses above overbought level with adaptive threshold
        rsi_sell_signal = previous['rsi'] < rsi_overbought_adjusted and current['rsi'] >= rsi_overbought_adjusted
        
        # Condition 2: Price is near Bollinger upper band with adaptive threshold
        bb_sell_signal = current['close'] >= current['bb_upper'] * bb_upper_threshold
        
        # Condition 3: Short EMA crosses below Medium EMA (bearish momentum)
        ema_cross_sell = previous['ema_short'] >= previous['ema_medium'] and current['ema_short'] < current['ema_medium']
        
        # Condition 4: MACD histogram turns negative
        macd_sell_signal = previous['macd_hist'] > 0 and current['macd_hist'] < 0
        
        # Condition 5: Stochastic crosses below 80 with adaptive threshold
        stoch_upper_threshold = 75 if is_high_volatility else 80  # 75 vs 80 - sell earlier on volatile coins
        stoch_sell_signal = previous['stoch_k'] > stoch_upper_threshold and current['stoch_k'] <= stoch_upper_threshold
        
        # Condition 6: Detecting volatility contraction - good for taking profits
        vol_contraction = current['volatility'] < previous['volatility'] * 0.8  # 20% decrease in volatility
        
        # Melhorar lógica de venda para ser menos restritiva
        sell_conditions = [rsi_sell_signal, bb_sell_signal, ema_cross_sell, macd_sell_signal, stoch_sell_signal, vol_contraction]
        
        # Tornar venda técnica mais flexível - basta um sinal forte
        # Obs: A maior parte das vendas virá do trailing stop ajustado ou target
        min_sell_conditions = 1 if is_high_volatility else 2
        sell_signal = sum(sell_conditions) >= min_sell_conditions
        
        # Set the signal
        if buy_signal:
            data.loc[data.index[-1], 'signal'] = 1
            self.logger.info(f"BUY signal generated at price {current['close']}")
            self.logger.debug(f"Buy conditions: RSI={current['rsi']:.2f}, BB_lower={current['bb_lower']:.2f}, Price={current['close']:.2f}")
        elif sell_signal:
            data.loc[data.index[-1], 'signal'] = -1
            self.logger.info(f"SELL signal generated at price {current['close']}")
            self.logger.debug(f"Sell conditions: RSI={current['rsi']:.2f}, BB_upper={current['bb_upper']:.2f}, Price={current['close']:.2f}")
        
        return data
    
    def should_buy(self, df):
        """Determine if we should buy based on the current signals"""
        data = self.generate_signals(df)
        
        # Check the last row for a buy signal
        if data.iloc[-1]['signal'] == 1:
            return True
        return False
    
    def should_sell(self, df):
        """Determine if we should sell based on the current signals"""
        data = self.generate_signals(df)
        
        # Check the last row for a sell signal
        if data.iloc[-1]['signal'] == -1:
            return True
        return False