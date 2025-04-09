from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.enums import *
import pandas as pd
import logging
import time
import math
import threading
from datetime import datetime, timedelta

class BinanceClient:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger('RoboCriptoCL.BinanceClient')
        
        # Default time offset
        self.time_offset = 0
        
        # Rate limiting protection
        self.request_weight = 0
        self.request_count = 0
        self.last_request_reset = datetime.now()
        self.rate_limit_lock = threading.Lock()  # Lock para concorrência
        self.rate_limit_wait = False
        self.max_weight_per_minute = 1000  # Valor máximo de peso por minuto
        
        # Cache para dados frequentemente acessados
        self.cache = {
            'account_balance': {'data': None, 'timestamp': None, 'expiry': 10},  # Expiração em segundos
            'ticker_prices': {'data': {}, 'timestamp': None, 'expiry': 5},
            'historical_klines': {},
            'symbol_info': {}
        }
        
        # Lista de símbolos com problemas para evitar operações repetidas com erro
        self.problem_symbols = {}  # {symbol: {'reason': '...', 'timestamp': datetime}}
        
        # Lista de símbolos com sinais recentes para evitar múltiplas compras seguidas
        self.recent_signals = {}  # {symbol: timestamp}
        
        # Initialize Binance client with higher recv_window to address time sync issues
        self.client = Client(config.api_key, config.api_secret, tld='com')
        self.client.options = {'recvWindow': 60000, 'timeout': 30}
        
        # Sync time with Binance server
        self._sync_time()
        
        # Test connectivity
        try:
            self._make_request(self.client.ping, weight=1)
            self.logger.info("Successfully connected to Binance API")
            
            # Get time difference between local and server
            server_time = self._make_request(self.client.get_server_time, weight=1)
            local_time = int(time.time() * 1000)
            time_diff = local_time - server_time['serverTime']
            self.logger.info(f"Time difference with Binance server: {time_diff} ms")
            
            # Get account info to verify API key permissions
            try:
                account_info = self._make_request(self.client.get_account, weight=10)
                self.logger.info(f"Account info received successfully")
                
                # Log da estrutura da resposta para debug
                if isinstance(account_info, dict):
                    self.logger.debug(f"Account info structure: {list(account_info.keys())}")
                    
                    if 'status' in account_info:
                        self.logger.info(f"Account status: {account_info['status']}")
                    elif 'accountType' in account_info:  # Novo formato possível
                        self.logger.info(f"Account type: {account_info['accountType']}")
                else:
                    self.logger.info(f"Unexpected account info format: {type(account_info)}")
                    
            except Exception as e:
                self.logger.error(f"Error retrieving account info: {e}")
                raise
            
        except BinanceAPIException as e:
            self.logger.error(f"Failed to connect to Binance API: {e}")
            raise
        
        # Initialize active coins
        self.active_coins = []
        self.all_tickers = {}
        
        # Track orders by coin
        self.open_orders = {}  # {symbol: [orders]}
        
        # Trade history by coin
        self.trade_history = {}  # {symbol: [trades]}
        
        # Get all available trading pairs for our quote asset
        self._update_all_tickers()
        
        # Select initial active coins
        self.select_active_coins()
    
    def _make_request(self, request_func, weight=1, *args, **kwargs):
        """Executa uma requisição para a API da Binance com controle de rate limit"""
        # Verificar se precisamos esperar para respeitar os limites
        with self.rate_limit_lock:
            # Resetar contador a cada minuto
            now = datetime.now()
            if (now - self.last_request_reset).total_seconds() > 60:
                self.request_weight = 0
                self.request_count = 0
                self.last_request_reset = now
                
            # Verificar se estamos próximos do limite
            if self.request_weight + weight > self.max_weight_per_minute:
                # Calcular quanto tempo falta para o próximo reset
                time_to_wait = 60 - (now - self.last_request_reset).total_seconds()
                if time_to_wait > 0:
                    self.logger.warning(f"Rate limit approaching, waiting {time_to_wait:.1f}s before next request")
                    self.rate_limit_wait = True
                    time.sleep(time_to_wait)
                    
                    # Reset após espera
                    self.request_weight = 0
                    self.request_count = 0
                    self.last_request_reset = datetime.now()
                    self.rate_limit_wait = False
            
            # Incrementar contadores
            self.request_weight += weight
            self.request_count += 1
        
        # Agora podemos fazer a requisição
        try:
            return request_func(*args, **kwargs)
        except BinanceAPIException as e:
            # Se for erro de rate limit, marcar para esperar mais
            if "-1003" in str(e):
                self.logger.warning(f"Rate limit exceeded: {e}")
                # Extrair tempo de ban, se disponível
                try:
                    ban_message = str(e)
                    if "IP banned until" in ban_message:
                        ban_time_ms = int(ban_message.split("IP banned until ")[1].split(".")[0])
                        ban_time = datetime.fromtimestamp(ban_time_ms / 1000)
                        wait_seconds = (ban_time - datetime.now()).total_seconds()
                        
                        if wait_seconds > 0:
                            self.logger.warning(f"API banned. Will wait for ban to expire: {wait_seconds:.1f}s")
                            time.sleep(min(wait_seconds, 60))  # Esperar no máximo 60 segundos
                except:
                    # Se não conseguir extrair, esperar 60 segundos
                    time.sleep(60)
                    
                # Redefinir contadores
                with self.rate_limit_lock:
                    self.request_weight = 0
                    self.request_count = 0
                    self.last_request_reset = datetime.now()
            
            # Propagar o erro
            raise
    
    def _sync_time(self):
        """
        Synchronize time with Binance server
        """
        try:
            # Get Binance server time
            server_time = self._make_request(self.client.get_server_time, weight=1)
            server_timestamp = server_time['serverTime']
            
            # Calculate difference with local time
            local_timestamp = int(time.time() * 1000)
            self.time_offset = local_timestamp - server_timestamp
            
            self.logger.info(f"Time offset with Binance server: {self.time_offset} ms")
            
        except BinanceAPIException as e:
            self.logger.error(f"Failed to sync time with Binance server: {e}")
            self.time_offset = 0
    
    def _get_timestamp(self):
        """
        Get timestamp adjusted for Binance server time difference
        """
        return int(time.time() * 1000) - self.time_offset
        
    def _update_all_tickers(self):
        """Update all available tickers for our quote asset"""
        try:
            # Get all ticker prices
            prices = self.client.get_all_tickers()
            self.all_tickers = {ticker['symbol']: float(ticker['price']) for ticker in prices}
            
            # Get 24hr stats for all pairs
            stats = self.client.get_ticker()
            
            # Filter for our quote asset
            self.ticker_stats = {}
            for stat in stats:
                symbol = stat['symbol']
                if symbol.endswith(self.config.quote_asset):
                    base_asset = symbol[:-len(self.config.quote_asset)]
                    
                    # Skip pairs in exclude list
                    if base_asset in self.config.exclude_coins:
                        continue
                    
                    # Calculate additional stats
                    price = float(stat['lastPrice'])
                    volume_24h = float(stat['quoteVolume'])  # Volume in quote asset (USDT)
                    price_change_pct = float(stat['priceChangePercent'])
                    
                    # Store relevant info
                    self.ticker_stats[symbol] = {
                        'price': price,
                        'volume_24h': volume_24h,
                        'price_change_24h_pct': price_change_pct,
                        'base_asset': base_asset,
                        'symbol': symbol
                    }
            
            self.logger.info(f"Updated ticker stats for {len(self.ticker_stats)} pairs with {self.config.quote_asset}")
            
        except BinanceAPIException as e:
            self.logger.error(f"Failed to get ticker data: {e}")
            raise
            
    def select_active_coins(self):
        """Select active coins based on volume, trend, and volatility"""
        try:
            # Update tickers first
            self._update_all_tickers()
            
            # Filter stable coins that we want to exclude
            filtered_pairs = {}
            for symbol, stats in self.ticker_stats.items():
                base_asset = stats['base_asset']
                
                # Excluir stablecoins ou pares específicos
                if symbol.endswith('USDT') and (
                    'USD' in base_asset or  # BUSD, USDC, TUSD, etc.
                    base_asset in ['DAI', 'PAX', 'SUSD', 'USDK', 'GUSD', 'HUSD', 'USDN'] or
                    symbol in ['BUSDUSDT', 'USDCUSDT', 'TUSDUSDT', 'DAIUSDT']
                ):
                    self.logger.debug(f"Skipping stablecoin pair: {symbol}")
                    continue
                
                # Excluir moedas que sabemos que têm problemas persistentes
                if symbol in self.problem_symbols:
                    problem = self.problem_symbols[symbol]
                    problem_time = problem['timestamp']
                    expiry_hours = problem.get('expiry_hours', 24)
                    
                    # Se o problema ainda é recente, pular
                    time_since_problem = (datetime.now() - problem_time).total_seconds() / 3600
                    if time_since_problem < expiry_hours:
                        self.logger.debug(f"Skipping problematic pair: {symbol} - {problem['reason']} ({time_since_problem:.1f}h ago)")
                        continue
                    else:
                        # Problema expirou, remover da lista
                        del self.problem_symbols[symbol]
                
                # Include pair if it has sufficient volume
                if stats['volume_24h'] >= self.config.min_volume_24h:
                    filtered_pairs[symbol] = stats
            
            self.logger.info(f"Found {len(filtered_pairs)} non-stablecoin pairs with sufficient volume")
            
            # Calculate volatility score for ranking
            for symbol, stats in filtered_pairs.items():
                # Get volatility data if available (24h price change as absolute value)
                volatility = abs(stats['price_change_24h_pct'])
                stats['volatility'] = volatility
                
                # Calculate a combined score (volume + volatility)
                # Normalize volume (0-100) and add weighted volatility
                volume_score = min(100, (stats['volume_24h'] / self.config.min_volume_24h) * 10)
                volatility_score = min(100, volatility * 2)  # Weight volatility
                
                # Combined score favors both volume and volatility
                stats['score'] = (volume_score * 0.6) + (volatility_score * 0.4)
            
            # Check if we need to enforce uptrend requirement
            high_volume_pairs = filtered_pairs
            if self.config.uptrend_required:
                # Keep only pairs in uptrend (positive 24h change)
                uptrend_pairs = {}
                for symbol, stats in filtered_pairs.items():
                    if stats['price_change_24h_pct'] > 0:
                        uptrend_pairs[symbol] = stats
                
                high_volume_pairs = uptrend_pairs
                self.logger.info(f"Filtered to {len(high_volume_pairs)} pairs in uptrend")
            
            # Sort by combined score (descending)
            sorted_pairs = sorted(
                high_volume_pairs.items(), 
                key=lambda x: x[1]['score'], 
                reverse=True
            )
            
            # First, include forced pairs from config
            new_active_coins = []
            for base_asset in self.config.include_coins:
                symbol = f"{base_asset}{self.config.quote_asset}"
                if symbol in self.ticker_stats:
                    # Check if it meets minimum requirements
                    stats = self.ticker_stats[symbol]
                    if stats['volume_24h'] >= self.config.min_volume_24h:
                        if not self.config.uptrend_required or stats['price_change_24h_pct'] > 0:
                            new_active_coins.append(symbol)
                            self.logger.info(f"Including required coin: {symbol}")
                    else:
                        self.logger.warning(f"Required coin {symbol} doesn't meet volume requirements")
                else:
                    self.logger.warning(f"Required coin {symbol} not found on exchange")
            
            # Then add top pairs by volume until we reach max_active_coins
            remaining_slots = self.config.max_active_coins - len(new_active_coins)
            for symbol, stats in sorted_pairs:
                # Skip if already included
                if symbol in new_active_coins:
                    continue
                
                # Add to active coins
                new_active_coins.append(symbol)
                
                # Break if we've reached the limit
                if len(new_active_coins) >= self.config.max_active_coins:
                    break
            
            # Log the changes
            added = set(new_active_coins) - set(self.active_coins)
            removed = set(self.active_coins) - set(new_active_coins)
            
            if added:
                self.logger.info(f"Added coins: {', '.join(added)}")
            if removed:
                self.logger.info(f"Removed coins: {', '.join(removed)}")
                
                # Close positions for removed coins
                for symbol in removed:
                    if symbol in self.open_orders and self.open_orders[symbol]:
                        self.logger.info(f"Closing positions for removed coin: {symbol}")
                        self.sell_all_positions(symbol)
            
            # Update active coins
            self.active_coins = new_active_coins
            
            # Initialize open orders for new coins
            for symbol in self.active_coins:
                if symbol not in self.open_orders:
                    self.open_orders[symbol] = []
                if symbol not in self.trade_history:
                    self.trade_history[symbol] = []
            
            self.logger.info(f"Active coins updated: {', '.join(self.active_coins)}")
            return self.active_coins
            
        except Exception as e:
            self.logger.error(f"Error selecting active coins: {e}")
            return self.active_coins
    
    def get_ticker_price(self, symbol):
        """Get current price for a trading pair with cache support"""
        cache_data = self.cache['ticker_prices']
        
        # Verificar se temos o símbolo em cache válido
        if symbol in cache_data['data'] and cache_data['timestamp']:
            cache_age = (datetime.now() - cache_data['timestamp']).total_seconds()
            
            # Se o cache ainda é válido, retornar dados do cache
            if cache_age < cache_data['expiry']:
                return cache_data['data'][symbol]
        
        # Cache expirado ou inválido, buscar dados novos
        try:
            # Se não atualizamos o cache há mais de 5 segundos, buscar todos os preços
            if not cache_data['timestamp'] or (datetime.now() - cache_data['timestamp']).total_seconds() > 5:
                # Atualizar todos os preços de uma vez (mais eficiente)
                all_tickers = self._make_request(self.client.get_all_tickers, weight=2)
                
                # Atualizar o cache completo
                prices = {ticker['symbol']: float(ticker['price']) for ticker in all_tickers}
                self.cache['ticker_prices']['data'] = prices
                self.cache['ticker_prices']['timestamp'] = datetime.now()
                
                # Retornar o preço específico solicitado
                if symbol in prices:
                    return prices[symbol]
                return None
            else:
                # Buscar apenas o preço do símbolo solicitado
                ticker = self._make_request(self.client.get_symbol_ticker, weight=1, symbol=symbol)
                price = float(ticker['price'])
                
                # Atualizar apenas esse símbolo no cache
                self.cache['ticker_prices']['data'][symbol] = price
                
                return price
                
        except BinanceAPIException as e:
            self.logger.error(f"Failed to get ticker price for {symbol}: {e}")
            
            # Se temos um valor em cache, usar mesmo que expirado
            if symbol in cache_data['data']:
                self.logger.warning(f"Using expired price cache for {symbol} due to API error")
                return cache_data['data'][symbol]
                
            return None
    
    def get_historical_klines(self, symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=100):
        """Get historical candlestick data with cache support"""
        cache_key = f"{symbol}_{interval}_{limit}"
        
        # Verificar se temos dados em cache
        if cache_key in self.cache['historical_klines']:
            cache_entry = self.cache['historical_klines'][cache_key]
            cache_age = (datetime.now() - cache_entry['timestamp']).total_seconds()
            
            # Para 1m usamos cache mais curto, para timeframes maiores podemos usar cache mais longo
            cache_expiry = 10 if interval == Client.KLINE_INTERVAL_1MINUTE else 30
            
            # Se o cache ainda é válido, retornar dados do cache
            if cache_age < cache_expiry:
                return cache_entry['data'].copy()  # Retornar uma cópia para evitar modificação do cache
        
        # Cache expirado ou inválido, buscar dados novos
        try:
            klines = self._make_request(
                self.client.get_klines,
                weight=5,
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            # Convert to pandas DataFrame
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # Convert types
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            # Atualizar o cache
            self.cache['historical_klines'][cache_key] = {
                'data': df.copy(),
                'timestamp': datetime.now()
            }
                
            return df
            
        except BinanceAPIException as e:
            self.logger.error(f"Failed to get historical data for {symbol}: {e}")
            
            # Se temos um valor em cache, usar mesmo que expirado
            if cache_key in self.cache['historical_klines']:
                self.logger.warning(f"Using expired klines cache for {symbol} due to API error")
                return self.cache['historical_klines'][cache_key]['data'].copy()
                
            return pd.DataFrame()
    
    def _check_symbol_problems(self, symbol):
        """
        Verifica se um símbolo tem problemas conhecidos antes de tentar operar
        Retorna: None se não há problemas, ou string com o motivo se há problemas
        """
        # Verificar se está na lista de problemas
        if symbol in self.problem_symbols:
            problem = self.problem_symbols[symbol]
            problem_time = problem['timestamp']
            expiry_hours = problem.get('expiry_hours', 24)
            
            # Verificar se o problema expirou
            time_since_problem = (datetime.now() - problem_time).total_seconds() / 3600  # em horas
            
            if time_since_problem < expiry_hours:
                # Problema ainda está ativo
                return problem['reason']
            else:
                # Problema expirou, remover da lista
                del self.problem_symbols[symbol]
                self.logger.info(f"Problem for {symbol} has expired after {time_since_problem:.1f} hours. Removed from problem list.")
                return None
        
        # Verificar se tivemos sinais recentes para este símbolo (para evitar compras múltiplas)
        if symbol in self.recent_signals:
            signal_time = self.recent_signals[symbol]
            minutes_since_signal = (datetime.now() - signal_time).total_seconds() / 60
            
            # Não permitir mais de um sinal a cada 15 minutos para o mesmo símbolo
            if minutes_since_signal < 15:
                return f"Recent signal ({minutes_since_signal:.1f} minutes ago)"
        
        return None
    
    def place_buy_order(self, symbol):
        """Place a market buy order"""
        # Verificar problemas conhecidos com este símbolo
        problem = self._check_symbol_problems(symbol)
        if problem:
            self.logger.warning(f"Skipping buy for {symbol} due to known problem: {problem}")
            return None
        
        try:
            # Extract base asset from symbol
            base_asset = symbol[:-len(self.config.quote_asset)]
            
            # Contar quantas ordens abertas realmente existem (não as que já foram vendidas)
            active_orders = len(self.open_orders.get(symbol, []))
            
            # Check if max orders reached for this coin
            if active_orders >= self.config.max_orders_per_coin:
                self.logger.warning(f"Maximum number of orders ({self.config.max_orders_per_coin}) reached for {symbol}. Skipping buy.")
                return None
            
            # Get current price
            current_price = self.get_ticker_price(symbol)
            if not current_price:
                return None
            
            # Get account balance
            balances = self.get_account_balance()
            if not balances or self.config.quote_asset not in balances:
                self.logger.error(f"Could not get balance for {self.config.quote_asset}")
                return None
            
            # Verificar se temos saldo mínimo suficiente para operar
            quote_balance = balances[self.config.quote_asset]['free']
            min_balance_required = self.config.min_balance_required if hasattr(self.config, 'min_balance_required') else 10.0
            
            if quote_balance < min_balance_required:
                self.logger.warning(f"Available balance ({quote_balance} {self.config.quote_asset}) below minimum required ({min_balance_required}). Skipping buy.")
                return None
            
            # Calculate quantity based on percentage of available balance
            quote_amount = quote_balance * self.config.trading_amount_percent
            
            # Convert to base asset quantity
            quantity = quote_amount / current_price
            
            # Get symbol info to correctly format quantity - usando a função com cache
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                self.logger.error(f"Failed to get symbol info for {symbol}")
                return None
                
            # Obter e validar os filtros da exchange
            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            min_notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
            min_qty_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            
            # Verificar quantidade mínima
            if min_qty_filter:
                min_qty = float(min_qty_filter.get('minQty', 0))
                if quantity < min_qty:
                    self.logger.warning(f"Order quantity {quantity} below minimum {min_qty} for {symbol}")
                    # Tentar ajustar para o mínimo permitido
                    if quote_amount >= min_qty * current_price * 1.05:  # Dar 5% de margem
                        quantity = min_qty
                        self.logger.info(f"Adjusted quantity to minimum allowed: {min_qty}")
                    else:
                        self.logger.warning(f"Not enough funds to meet minimum quantity for {symbol}")
                                    # Adicionar à lista de símbolos com problemas para evitar futuras tentativas
                        self.problem_symbols[symbol] = {
                            'reason': 'Minimum quantity issues',
                            'timestamp': datetime.now(),
                            'expiry_hours': 24  # Não tentar novamente por 24 horas
                        }
                        if hasattr(self, 'coin_analysis'):
                            self.coin_analysis[symbol] = {
                                'status': 'Skipped - Minimum quantity issues',
                                'last_update': datetime.now()
                            }
                        return None
            
            # Verificar e ajustar para o step size correto
            if lot_size_filter:
                # Format quantity to appropriate decimal places
                step_size = float(lot_size_filter['stepSize'])
                original_quantity = quantity
                quantity = self._format_quantity(quantity, step_size)
                
                # Log se houver ajuste significativo
                if abs(original_quantity - quantity) / original_quantity > 0.01:  # Mais de 1% de diferença
                    self.logger.info(f"Quantity adjusted from {original_quantity} to {quantity} due to lot size restrictions")
            
            # Check minimum notional value (valor mínimo da ordem)
            if min_notional_filter:
                min_notional = float(min_notional_filter['minNotional'])
                order_value = quantity * current_price
                
                if order_value < min_notional:
                    self.logger.warning(f"Order value {order_value} {self.config.quote_asset} below minimum notional value ({min_notional} {self.config.quote_asset}) for {symbol}")
                    
                    # Verificar se podemos aumentar a ordem para atender o mínimo
                    if quote_balance >= min_notional * 1.05:  # 5% de margem
                        # Calcular nova quantidade para atingir o valor mínimo
                        new_quantity = min_notional / current_price
                        
                        # Ajustar para o step size
                        if lot_size_filter:
                            new_quantity = self._format_quantity(new_quantity, step_size)
                            
                        # Verificar se a nova quantidade é válida
                        if new_quantity > 0 and new_quantity * current_price >= min_notional:
                            self.logger.info(f"Adjusted quantity from {quantity} to {new_quantity} to meet minimum notional value")
                            quantity = new_quantity
                        else:
                            self.logger.warning(f"Cannot adjust quantity properly for {symbol} to meet minimum requirements")
                            # Adicionar à lista de símbolos com problemas
                            self.problem_symbols[symbol] = {
                                'reason': 'Minimum value issues',
                                'timestamp': datetime.now(),
                                'expiry_hours': 24  # Não tentar novamente por 24 horas
                            }
                            if hasattr(self, 'coin_analysis'):
                                self.coin_analysis[symbol] = {
                                    'status': 'Skipped - Minimum value issues',
                                    'last_update': datetime.now()
                                }
                            return None
                    else:
                        self.logger.warning(f"Not enough funds to meet minimum notional value for {symbol}")
                        # Adicionar à lista de símbolos com problemas
                        self.problem_symbols[symbol] = {
                            'reason': 'Insufficient funds',
                            'timestamp': datetime.now(),
                            'expiry_hours': 1  # Tentar novamente após 1 hora (pode ser que fundos fiquem disponíveis)
                        }
                        if hasattr(self, 'coin_analysis'):
                            self.coin_analysis[symbol] = {
                                'status': 'Skipped - Insufficient funds',
                                'last_update': datetime.now()
                            }
                        return None
            
            # Verificar volatilidade da moeda para configurar targets
            # Obter dados históricos recentes
            klines = self.get_historical_klines(
                symbol=symbol,
                interval=Client.KLINE_INTERVAL_1MINUTE, 
                limit=30
            )
            
            # Calcular volatilidade (desvio padrão dos retornos em %)
            if not klines.empty and len(klines) >= 20:
                # Converter preços para retornos
                returns = klines['close'].pct_change() * 100
                
                # Calcular volatilidade como desvio padrão dos retornos
                volatility = returns.iloc[1:].std()  # Ignorar o primeiro valor (NaN)
                
                # Verificar se esta é uma moeda de alta volatilidade
                is_high_volatility = volatility > self.config.high_volatility_threshold
                self.logger.info(f"{symbol} volatility: {volatility:.2f}% - {'High' if is_high_volatility else 'Normal'} volatility coin")
            else:
                # Se não temos dados suficientes, assumir volatilidade normal
                is_high_volatility = False
                self.logger.info(f"Insufficient data to calculate volatility for {symbol}, assuming normal volatility")
            
            # Usar parâmetros de profit/loss apropriados com base na volatilidade
            if is_high_volatility:
                profit_target = self.config.high_vol_profit_target
                stop_loss = self.config.high_vol_stop_loss
            else:
                profit_target = self.config.profit_target
                stop_loss = self.config.stop_loss
                
            # Calculate target sell price and stop loss with adapted parameters
            target_price = current_price * (1 + profit_target)
            stop_loss_price = current_price * (1 - stop_loss)
            
            # Place market buy order
            order = self.client.create_order(
                symbol=symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            
            # Enhance order with tracking information
            order['entry_price'] = current_price
            order['target_price'] = target_price
            order['stop_loss_price'] = stop_loss_price
            order['initial_stop_loss'] = stop_loss_price  # Guardar o stop loss inicial
            order['status'] = 'ACTIVE'
            order['profit_loss'] = 0
            order['symbol'] = symbol
            order['base_asset'] = base_asset
            order['buy_time'] = datetime.now()
            order['highest_price'] = current_price  # Para trailing stop
            order['trailing_activated'] = False  # Flag para indicar se o trailing stop está ativo
            
            # Adicionar informações de volatilidade para ajustar trailing stop
            if 'volatility' in locals():
                order['volatility'] = volatility
                order['is_high_volatility'] = is_high_volatility
            else:
                order['volatility'] = 0
                order['is_high_volatility'] = False
            
            self.logger.info(f"Buy order placed for {symbol}: {quantity} {base_asset} at ~{current_price} {self.config.quote_asset}")
            
            # Add to open orders
            if symbol not in self.open_orders:
                self.open_orders[symbol] = []
            self.open_orders[symbol].append(order)
            
            # Add to trade history
            if symbol not in self.trade_history:
                self.trade_history[symbol] = []
            
            self.trade_history[symbol].append({
                'type': 'BUY',
                'time': datetime.now(),
                'price': current_price,
                'quantity': float(order['executedQty']),
                'total': float(order['cummulativeQuoteQty']),
                'order_id': order['orderId'],
                'symbol': symbol  # Adicionando o símbolo explicitamente
            })
            
            # Registrar o símbolo como tendo um sinal recente para evitar múltiplas compras seguidas
            self.recent_signals[symbol] = datetime.now()
            
            # Se estava na lista de problemas, remover
            if symbol in self.problem_symbols:
                del self.problem_symbols[symbol]
            
            return order
            
        except BinanceAPIException as e:
            self.logger.error(f"Failed to place buy order for {symbol}: {e}")
            
            # Registrar o problema para evitar tentativas repetidas
            error_msg = str(e)
            
            if "Invalid quantity" in error_msg:
                # Problema de quantidade mínima
                self.problem_symbols[symbol] = {
                    'reason': 'Invalid quantity',
                    'timestamp': datetime.now(),
                    'expiry_hours': 24
                }
            elif "MIN_NOTIONAL" in error_msg or "NOTIONAL" in error_msg:
                # Problema de valor mínimo
                self.problem_symbols[symbol] = {
                    'reason': 'Minimum order value not met',
                    'timestamp': datetime.now(),
                    'expiry_hours': 24
                }
            else:
                # Outros erros
                self.problem_symbols[symbol] = {
                    'reason': f"API error: {error_msg[:50]}...",
                    'timestamp': datetime.now(),
                    'expiry_hours': 1  # Tentar novamente em 1 hora para outros erros
                }
                
            if hasattr(self, 'coin_analysis') and symbol in getattr(self, 'coin_analysis', {}):
                self.coin_analysis[symbol]['status'] = f"Error: {error_msg[:50]}..."
                
            return None
    
    def _format_quantity(self, quantity, step_size):
        """Format quantity according to exchange requirements"""
        if step_size == 0:
            return quantity
            
        # Determine a precisão baseada no step_size
        precision = int(round(-math.log10(float(step_size))))
        
        # Arredonda para baixo para o múltiplo mais próximo de step_size
        truncated = math.floor(quantity / float(step_size)) * float(step_size)
        
        # Formata para o número correto de casas decimais
        formatted = "{:0.{}f}".format(truncated, precision)
        
        return float(formatted)
    
    def place_sell_order(self, symbol, order_id):
        """Place a market sell order for a specific open order"""
        # Verificar se já estamos tentando vender esta ordem
        for o in self.open_orders.get(symbol, []):
            if o['orderId'] == order_id and o.get('selling_in_progress', False):
                self.logger.debug(f"Sell already in progress for {symbol} order {order_id}, skipping")
                return None

        try:
            # Find the order
            order = None
            for o in self.open_orders.get(symbol, []):
                if o['orderId'] == order_id:
                    order = o
                    # Marcar que estamos tentando vender para evitar tentativas múltiplas
                    o['selling_in_progress'] = True
                    break
            
            if not order:
                self.logger.error(f"Order ID {order_id} not found in open orders for {symbol}")
                return None
            
            # Extract base asset from symbol
            base_asset = symbol[:-len(self.config.quote_asset)]
            
            # Verificar saldo atual da moeda base
            balances = self.get_account_balance()
            actual_balance = balances.get(base_asset, {}).get('free', 0)
            
            # Get the quantity from the original order
            order_quantity = float(order['executedQty'])
            
            # Verificar se temos saldo suficiente e ajustar se necessário
            if actual_balance < order_quantity:
                if actual_balance <= 0:
                    self.logger.warning(f"No {base_asset} balance available to sell for order {order_id}. Removing from tracking.")
                    # Remover ordem dos registros já que não temos a moeda
                    self.open_orders[symbol] = [o for o in self.open_orders[symbol] if o['orderId'] != order_id]
                    return None
                else:
                    self.logger.warning(f"Insufficient {base_asset} balance. Adjusting from {order_quantity} to {actual_balance}")
                    quantity = actual_balance
            else:
                quantity = order_quantity
            
            # Formatar a quantidade corretamente
            symbol_info = self.client.get_symbol_info(symbol)
            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            
            if lot_size_filter:
                # Format quantity to appropriate decimal places
                step_size = float(lot_size_filter['stepSize'])
                quantity = self._format_quantity(quantity, step_size)
            
            # Place market sell order
            sell_order = self.client.create_order(
                symbol=symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            
            # Get current price
            current_price = self.get_ticker_price(symbol)
            
            # Calculate profit/loss including fees
            entry_price = order['entry_price']
            fee_percentage = self.config.fee_percentage if hasattr(self.config, 'fee_percentage') else 0.1
            total_fee_percentage = fee_percentage * 2  # Both buy and sell
            profit_loss = ((current_price - entry_price) / entry_price * 100) - total_fee_percentage
            
            self.logger.info(f"Sell order placed for {symbol}: {quantity} {base_asset} at ~{current_price} {self.config.quote_asset} (P/L: {profit_loss:.2f}%)")
            
            # Remove from open orders
            # Primeiro, limpe a flag de venda em andamento em caso de erro
            for o in self.open_orders.get(symbol, []):
                if o['orderId'] == order_id:
                    o['selling_in_progress'] = False
                    break
                    
            # Remover a ordem completamente da lista
            self.open_orders[symbol] = [o for o in self.open_orders[symbol] if o['orderId'] != order_id]
            
            # Add profit/loss to sell order
            sell_order['profit_loss'] = profit_loss
            sell_order['entry_price'] = entry_price
            sell_order['exit_price'] = current_price
            sell_order['symbol'] = symbol
            sell_order['base_asset'] = base_asset
            
            # Add to trade history
            if symbol not in self.trade_history:
                self.trade_history[symbol] = []
            
            self.trade_history[symbol].append({
                'type': 'SELL',
                'time': datetime.now(),
                'price': current_price,
                'quantity': quantity,
                'total': float(sell_order['cummulativeQuoteQty']),
                'profit_loss': profit_loss,
                'order_id': sell_order['orderId'],
                'original_order_id': order_id,
                'symbol': symbol  # Adicionando o símbolo explicitamente
            })
            
            return sell_order
            
        except BinanceAPIException as e:
            self.logger.error(f"Failed to place sell order for {symbol}: {e}")
            
            # Limpar a flag de venda em andamento em caso de erro
            for o in self.open_orders.get(symbol, []):
                if o['orderId'] == order_id:
                    o['selling_in_progress'] = False
                    
                    # Se o erro for de saldo insuficiente e persistente, remover a ordem para evitar loops infinitos
                    if "-2010" in str(e) and "insufficient balance" in str(e).lower():
                        self.logger.warning(f"Insufficient balance error for {symbol} order {order_id}. Removing from tracking.")
                        self.open_orders[symbol] = [o for o in self.open_orders[symbol] if o['orderId'] != order_id]
                        
                        # Força uma sincronização imediata de todas as ordens para este símbolo
                        # já que provavelmente temos ordens fantasma
                        self._check_and_fix_ghost_orders(symbol)
                    break
                    
            return None
    
    def sell_all_positions(self, symbol=None):
        """
        Sell all open positions for a specific symbol or all symbols,
        including balances that podem não estar sendo rastreadas pelo bot
        
        Args:
            symbol: If provided, only sell positions for this symbol
        """
        results = []
        
        try:
            # Obter todos os saldos reais da conta
            balances = self.get_account_balance()
            if not balances:
                self.logger.error("Could not get account balances for selling positions")
                return results
                
            # Remover USDT da lista (nossa moeda base/quote)
            if self.config.quote_asset in balances:
                del balances[self.config.quote_asset]
                
            # Lista de símbolos para processar
            symbols_to_process = []
            
            # Se um símbolo específico foi fornecido
            if symbol:
                # Verificar se é um par válido
                if symbol.endswith(self.config.quote_asset):
                    symbols_to_process.append(symbol)
                else:
                    # Se é apenas o nome da moeda (ex: BTC), formar o par completo
                    full_symbol = f"{symbol}{self.config.quote_asset}"
                    symbols_to_process.append(full_symbol)
            else:
                # Processar todas as moedas com saldo
                for asset, balance_info in balances.items():
                    # Ignore moedas sem saldo disponível
                    if balance_info['free'] <= 0:
                        continue
                        
                    # Formar o par completo para venda
                    full_symbol = f"{asset}{self.config.quote_asset}"
                    symbols_to_process.append(full_symbol)
                    
                # Adicionar também todos os símbolos que temos em nosso tracking
                for tracked_symbol in self.open_orders.keys():
                    if tracked_symbol not in symbols_to_process:
                        symbols_to_process.append(tracked_symbol)
            
            self.logger.info(f"Selling all positions for {len(symbols_to_process)} symbols: {symbols_to_process}")
            
            # Processar cada símbolo
            for current_symbol in symbols_to_process:
                # Extrair o ativo base
                base_asset = current_symbol[:-len(self.config.quote_asset)]
                
                # Primeiro, vender ordens rastreadas pelo sistema
                if current_symbol in self.open_orders and self.open_orders[current_symbol]:
                    # Copy list to avoid modification during iteration
                    orders_to_sell = self.open_orders[current_symbol].copy()
                    
                    for order in orders_to_sell:
                        result = self.place_sell_order(current_symbol, order['orderId'])
                        if result:
                            results.append(result)
                
                # Depois, verificar se ainda há saldo remanescente e vender diretamente
                if base_asset in balances and balances[base_asset]['free'] > 0:
                    try:
                        # Obter saldo disponível
                        quantity = balances[base_asset]['free']
                        
                        # Verificar se o símbolo existe
                        symbol_info = self.get_symbol_info(current_symbol)
                        if not symbol_info:
                            self.logger.warning(f"Could not get symbol info for {current_symbol} to sell remaining balance")
                            continue
                        
                        # Formatar quantidade para o formato correto
                        lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                        if lot_size_filter:
                            step_size = float(lot_size_filter['stepSize'])
                            quantity = self._format_quantity(quantity, step_size)
                        
                        if quantity <= 0:
                            continue
                            
                        self.logger.info(f"Selling remaining balance of {quantity} {base_asset} not tracked by orders")
                        
                        # Criar ordem de venda direta
                        sell_order = self.client.create_order(
                            symbol=current_symbol,
                            side=SIDE_SELL,
                            type=ORDER_TYPE_MARKET,
                            quantity=quantity
                        )
                        
                        # Adicionar informações extras ao resultado
                        current_price = self.get_ticker_price(current_symbol)
                        sell_order['symbol'] = current_symbol
                        sell_order['base_asset'] = base_asset
                        
                        # Adicionar aos resultados
                        results.append(sell_order)
                        
                        # Adicionar ao histórico de trades
                        if current_symbol not in self.trade_history:
                            self.trade_history[current_symbol] = []
                        
                        self.trade_history[current_symbol].append({
                            'type': 'SELL',
                            'time': datetime.now(),
                            'price': current_price if current_price else 0,
                            'quantity': quantity,
                            'total': float(sell_order.get('cummulativeQuoteQty', 0)),
                            'profit_loss': 0,  # Não podemos calcular sem saber o preço de entrada
                            'order_id': sell_order['orderId'],
                            'original_order_id': 0,  # Não há ordem original
                            'symbol': current_symbol,  # Adicionando o símbolo explicitamente
                            'note': 'Sold remaining balance'
                        })
                        
                    except BinanceAPIException as e:
                        self.logger.error(f"Failed to sell remaining balance for {current_symbol}: {e}")
                
            # Atualizar balances após vender tudo
            self.get_account_balance()
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error in sell_all_positions: {e}")
            return results
    
    def check_order_status(self):
        """Check status of all open orders and update profit/loss"""
        # Lista para rastrear ordens que devem ser removidas
        orders_to_remove = {}  # {symbol: [order_ids]}
        
        for symbol, orders in self.open_orders.items():
            if not orders:
                continue
                
            # Inicializar lista para este símbolo
            if symbol not in orders_to_remove:
                orders_to_remove[symbol] = []
                
            current_price = self.get_ticker_price(symbol)
            if not current_price:
                continue
            
            # Copy list to avoid modification during iteration
            orders_copy = orders.copy()
            
            for order in orders_copy:
                # Verificar se esta ordem já está marcada para remoção
                if order['orderId'] in orders_to_remove.get(symbol, []):
                    continue
                    
                # Update profit/loss
                entry_price = order['entry_price']
                profit_loss = (current_price - entry_price) / entry_price * 100
                order['profit_loss'] = profit_loss
                
                # Verificar quantas tentativas de venda já foram feitas
                if 'sell_attempts' not in order:
                    order['sell_attempts'] = 0
                    
                # Se já tentamos vender muitas vezes sem sucesso, marcar para remoção
                if order.get('sell_attempts', 0) >= 3:
                    self.logger.warning(f"Order {order['orderId']} for {symbol} has {order['sell_attempts']} failed sell attempts. Removing from tracking.")
                    orders_to_remove[symbol].append(order['orderId'])
                    continue
                
                # Check if this is a new highest price for trailing stop
                if current_price > order.get('highest_price', 0):
                    order['highest_price'] = current_price
                    
                    # Check if we should activate trailing stop
                    if self.config.trailing_stop and not order.get('trailing_activated', False):
                        # Determinar o profit target para esta ordem específica
                        profit_target_value = self.config.high_vol_profit_target if order.get('is_high_volatility', False) else self.config.profit_target
                        
                        # Calculate how far along we are toward target (as percentage of target)
                        progress_to_target = profit_loss / (profit_target_value * 100)
                        
                        # Para moedas muito voláteis, reduzir o limite de ativação ainda mais
                        activation_threshold = self.config.trailing_stop_activation
                        if order.get('volatility', 0) > self.config.high_volatility_threshold * 1.5:  # Moedas extremamente voláteis
                            activation_threshold = self.config.trailing_stop_activation * 0.8  # Reduz em 20%
                        
                        # If we've reached the activation threshold
                        if progress_to_target >= activation_threshold:
                            # Activate trailing stop
                            order['trailing_activated'] = True
                            
                            # Adaptar a distância do trailing stop com base na volatilidade
                            trailing_distance = self.config.trailing_stop_distance
                            if order.get('is_high_volatility', False):
                                # Moedas mais voláteis precisam de mais espaço para variar
                                # mas também mantemos o trailing mais próximo para capturar lucros rapidamente
                                volatility_factor = min(order.get('volatility', 0) / self.config.high_volatility_threshold, 2.0)
                                trailing_distance = self.config.trailing_stop_distance * (1 + (volatility_factor - 1) * 0.3)
                            
                            new_stop_loss = current_price * (1 - trailing_distance)
                            
                            # Only move stop loss up, never down
                            if new_stop_loss > order['stop_loss_price']:
                                old_stop = order['stop_loss_price']
                                order['stop_loss_price'] = new_stop_loss
                                order['trailing_distance'] = trailing_distance  # Armazenar a distância escolhida
                                self.logger.info(f"Trailing stop activated for {symbol} order {order['orderId']}. Stop loss moved from {old_stop:.6f} to {new_stop_loss:.6f}")
                
                # If trailing stop is active, update stop loss as price moves up
                if order.get('trailing_activated', False):
                    # Usar a distância de trailing específica para esta ordem, se disponível
                    trailing_distance = order.get('trailing_distance', self.config.trailing_stop_distance)
                    
                    # Calculate new stop loss based on highest price
                    new_stop_loss = order['highest_price'] * (1 - trailing_distance)
                    
                    # Only move stop loss up, never down
                    if new_stop_loss > order['stop_loss_price']:
                        old_stop = order['stop_loss_price']
                        order['stop_loss_price'] = new_stop_loss
                        self.logger.debug(f"Trailing stop updated for {symbol} order {order['orderId']}. Stop loss moved from {old_stop:.6f} to {new_stop_loss:.6f}")
                
                # Check if target or stop loss hit
                # Evitar repetidas tentativas de venda se já estamos processando
                if order.get('selling_in_progress', False):
                    continue
                
                # Verificar preço alvo
                if current_price >= order['target_price']:
                    self.logger.info(f"Target price reached for {symbol} order {order['orderId']}. Selling position.")
                    result = self.place_sell_order(symbol, order['orderId'])
                    if result is None:
                        # Incrementar contador de tentativas de venda
                        order['sell_attempts'] = order.get('sell_attempts', 0) + 1
                        self.logger.warning(f"Failed to sell {symbol} order {order['orderId']}. Attempt {order['sell_attempts']}.")
                        
                        # Se falhou várias vezes, marcar para verificação mais detalhada
                        if order['sell_attempts'] >= 3:
                            self._check_and_fix_ghost_orders(symbol)
                    
                # Verificar stop loss    
                elif current_price <= order['stop_loss_price']:
                    # Log differently if this was a trailing stop or initial stop
                    if order.get('trailing_activated', False) and order['stop_loss_price'] > order.get('initial_stop_loss', 0):
                        self.logger.info(f"Trailing stop triggered for {symbol} order {order['orderId']} at {current_price:.6f}. Selling position with {profit_loss:.2f}% profit.")
                    else:
                        self.logger.info(f"Stop loss triggered for {symbol} order {order['orderId']}. Selling position.")
                    
                    result = self.place_sell_order(symbol, order['orderId'])
                    if result is None:
                        # Incrementar contador de tentativas de venda
                        order['sell_attempts'] = order.get('sell_attempts', 0) + 1
                        self.logger.warning(f"Failed to sell {symbol} order {order['orderId']}. Attempt {order['sell_attempts']}.")
                        
                        # Se falhou várias vezes, marcar para verificação mais detalhada
                        if order['sell_attempts'] >= 3:
                            self._check_and_fix_ghost_orders(symbol)
        
        # Remover ordens que foram marcadas para remoção
        for symbol, order_ids in orders_to_remove.items():
            if order_ids:
                self.logger.info(f"Removing {len(order_ids)} problematic orders for {symbol}")
                self.open_orders[symbol] = [o for o in self.open_orders[symbol] if o['orderId'] not in order_ids]
    
    def get_account_balance(self):
        """Get account balance for all assets with cache support"""
        # Verificar se temos dados em cache válidos
        cache_data = self.cache['account_balance']
        cache_age = 0
        
        if cache_data['data'] and cache_data['timestamp']:
            cache_age = (datetime.now() - cache_data['timestamp']).total_seconds()
            
            # Se o cache ainda é válido, retornar dados do cache
            if cache_age < cache_data['expiry']:
                return cache_data['data']
        
        # Cache expirado ou inválido, buscar dados novos
        try:
            # Registrar hora da tentativa para não sobrecarregar em caso de falha
            self.cache['account_balance']['timestamp'] = datetime.now()
            
            account = self._make_request(self.client.get_account, weight=10)
            balances = {}
            
            for balance in account['balances']:
                # Only include non-zero balances
                if float(balance['free']) > 0 or float(balance['locked']) > 0:
                    balances[balance['asset']] = {
                        'free': float(balance['free']),
                        'locked': float(balance['locked'])
                    }
            
            # Atualizar o cache
            self.cache['account_balance']['data'] = balances
            self.cache['account_balance']['timestamp'] = datetime.now()
            
            return balances
            
        except BinanceAPIException as e:
            self.logger.error(f"Failed to get account balance: {e}")
            
            # Se o cache for relativamente recente (menos de 60 segundos), usar mesmo expirado
            if cache_age < 60 and cache_data['data']:
                self.logger.warning(f"Using expired balance cache ({cache_age:.1f}s old) due to API error")
                return cache_data['data']
                
            return None
    
    def get_all_open_orders(self):
        """Get all open orders for all symbols"""
        all_orders = []
        for symbol, orders in self.open_orders.items():
            for order in orders:
                all_orders.append(order)
        return all_orders
    
    def get_trade_history(self, symbol=None):
        """Get trade history for a specific symbol or all symbols"""
        if symbol:
            return self.trade_history.get(symbol, [])
        
        # Combine all trade history
        all_trades = []
        for symbol, trades in self.trade_history.items():
            all_trades.extend(trades)
        
        # Sort by time (newest first)
        all_trades.sort(key=lambda x: x['time'], reverse=True)
        
        return all_trades
    
    def _check_and_fix_ghost_orders(self, symbol):
        """
        Verifica e corrige ordens fantasmas para um determinado símbolo.
        Este método é chamado quando detectamos um erro de saldo insuficiente,
        o que pode indicar que estamos rastreando ordens que já não existem.
        """
        self.logger.info(f"Checking for ghost orders for {symbol}")
        
        # Primeiro verificamos se há ordens rastreadas para este símbolo
        # Se não, não precisamos fazer nada
        tracked_orders = self.open_orders.get(symbol, [])
        if not tracked_orders:
            return
        
        # Extrair o ativo base do símbolo
        base_asset = symbol[:-len(self.config.quote_asset)]
        
        # Verificar saldo real disponível usando cache
        try:
            balances = self.get_account_balance()
            if not balances:
                self.logger.warning(f"Could not get balances to check ghost orders for {symbol}")
                return
                
            # Obter saldo real do ativo
            actual_balance = balances.get(base_asset, {}).get('free', 0)
            
            # Se não temos saldo, todas as ordens são fantasmas
            if actual_balance <= 0:
                if tracked_orders:
                    self.logger.warning(f"No {base_asset} balance available but have {len(tracked_orders)} tracked orders. Clearing all.")
                    self.open_orders[symbol] = []
                return
                
            # Verificar se o saldo total esperado excede o saldo real
            # Se a discrepância é muito grande, limpar todas as ordens sem fazer mais checagens
            expected_balance = sum(float(order['executedQty']) for order in tracked_orders if not order.get('selling_in_progress', False))
            
            # Se o saldo real é menos que 10% do esperado, provavelmente todas são fantasmas
            if actual_balance < expected_balance * 0.1:
                self.logger.warning(f"Major balance discrepancy for {base_asset}: expected {expected_balance}, have {actual_balance}. Clearing all orders.")
                self.open_orders[symbol] = []
                return
            
            # Se a discrepância é menor, verificar as ordens uma a uma
            # Verificar se há ordens muito antigas que podem ser ordens fantasmas
            ghost_orders = []
            now = datetime.now()
            
            for order in tracked_orders:
                # Se a ordem está marcada como em andamento para venda, ignorar
                if order.get('selling_in_progress', False):
                    continue
                
                # Se a ordem tem muitas tentativas de venda falhadas, é provavelmente fantasma
                if order.get('sell_attempts', 0) >= 3:
                    ghost_orders.append(order['orderId'])
                    continue
                
                # Se a ordem é muito antiga (mais de 1 dia), verificar se ainda existe
                order_time = order.get('buy_time', now)
                if isinstance(order_time, datetime) and (now - order_time).total_seconds() > 86400:
                    # Verificar se é uma ordem real
                    try:
                        # Obter ordens abertas só para este symbol para economizar rate
                        binance_open_orders = self._make_request(
                            self.client.get_open_orders,
                            weight=3,
                            symbol=symbol
                        )
                        real_order_ids = [o['orderId'] for o in binance_open_orders if o['side'] == 'BUY']
                        
                        if order['orderId'] not in real_order_ids:
                            ghost_orders.append(order['orderId'])
                            
                    except BinanceAPIException as e:
                        self.logger.error(f"Failed to check open orders for {symbol}: {e}")
            
            # Remover ordens fantasmas
            if ghost_orders:
                self.logger.warning(f"Found {len(ghost_orders)} ghost orders for {symbol}: {ghost_orders}")
                self.open_orders[symbol] = [o for o in tracked_orders if o['orderId'] not in ghost_orders]
                
            # Recalcular se necessário
            remaining_orders = self.open_orders.get(symbol, [])
            if remaining_orders:
                expected_balance = sum(float(order['executedQty']) for order in remaining_orders if not order.get('selling_in_progress', False))
                
                # Se ainda há discrepância, remover as ordens mais antigas primeiro
                if expected_balance > actual_balance * 1.02:  # Permitir 2% de margem
                    self.logger.warning(f"Balance discrepancy after removing ghosts for {base_asset}: expected {expected_balance}, have {actual_balance}")
                    
                    # Ordenar ordens por tempo (mais antigas primeiro)
                    remaining_orders.sort(key=lambda o: o.get('buy_time', datetime.now()))
                    
                    # Remover ordens antigas até que a soma seja compatível com o saldo real
                    while expected_balance > actual_balance * 1.02 and remaining_orders:
                        order_to_remove = remaining_orders[0]
                        order_qty = float(order_to_remove['executedQty'])
                        self.logger.warning(f"Removing old order {order_to_remove['orderId']} with qty {order_qty}")
                        remaining_orders.pop(0)
                        expected_balance -= order_qty
                    
                    # Atualizar lista final
                    self.open_orders[symbol] = remaining_orders
                    
        except Exception as e:
            self.logger.error(f"Error checking ghost orders for {symbol}: {e}")
    
    def get_symbol_info(self, symbol):
        """Get detailed information for a symbol with cache support"""
        # Verificar se temos dados em cache
        if symbol in self.cache['symbol_info']:
            # Symbol info não muda com frequência, cache por 24 horas
            cache_entry = self.cache['symbol_info'][symbol]
            cache_age = (datetime.now() - cache_entry['timestamp']).total_seconds()
            
            # Cache com validade de 24 horas (86400 segundos)
            if cache_age < 86400:
                return cache_entry['data']
        
        # Cache expirado ou inválido, buscar dados novos
        try:
            symbol_info = self._make_request(self.client.get_symbol_info, weight=2, symbol=symbol)
            
            # Atualizar o cache
            self.cache['symbol_info'][symbol] = {
                'data': symbol_info,
                'timestamp': datetime.now()
            }
            
            return symbol_info
            
        except BinanceAPIException as e:
            self.logger.error(f"Failed to get symbol info for {symbol}: {e}")
            
            # Se temos um valor em cache, usar mesmo que expirado
            if symbol in self.cache['symbol_info']:
                self.logger.warning(f"Using expired symbol info cache for {symbol} due to API error")
                return self.cache['symbol_info'][symbol]['data']
                
            return None