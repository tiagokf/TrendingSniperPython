import time
import logging
import threading
import pandas as pd
import math
import os
import json
from datetime import datetime, timedelta
from binance.client import Client

class TradeManager:
    def __init__(self, config, binance_client, strategy):
        self.config = config
        self.binance_client = binance_client
        self.strategy = strategy
        self.logger = logging.getLogger('RoboCriptoCL.TradeManager')
        
        # Criar o diretório de logs se não existir
        os.makedirs('logs', exist_ok=True)
        
        self.running = False
        self.thread = None
        
        # Performance tracking
        self.profit_loss = 0
        self.win_count = 0
        self.loss_count = 0
        self.last_update_time = None
        
        # Arquivo de log para desempenho
        self.performance_log = os.path.join('logs', 'performance.log')
        self.trade_log = os.path.join('logs', 'trades.log')
        
        # Data for trading and dashboard
        self.current_prices = {}  # {symbol: price}
        self.historical_data = {}  # {symbol: DataFrame}
        self.coin_analysis = {}   # {symbol: {uptrend: bool, last_signal: str, ...}}
        
        # Track last coin selection time
        self.last_coin_selection = datetime.now() - timedelta(hours=1)
        
        # Track last balance sync time
        self.last_balance_sync = datetime.now() - timedelta(minutes=30)
        
        # Flag para correção de inconsistências
        
        self.min_order_usdt = getattr(self.config, "min_order_usdt", 12)
        self.min_signal_interval_minutes = self.config.get("min_signal_interval_minutes", 1)
        self.last_signal_time = {}  # {symbol: datetime}

        self.sync_needed = True
    
    def start(self):
        """Start the trading bot"""
        if self.running:
            self.logger.warning("Trading bot is already running")
            return False
        
        self.running = True
        self.thread = threading.Thread(target=self._trading_loop)
        self.thread.daemon = True
        self.thread.start()
        
        self.logger.info("Trading bot started")
        return True
    
    def stop(self):
        """Stop the trading bot"""
        if not self.running:
            self.logger.warning("Trading bot is not running")
            return False
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
            self.thread = None
        
        self.logger.info("Trading bot stopped")
        return True
    
    def sell_all(self):
        """Sell all open positions"""
        results = self.binance_client.sell_all_positions()
        count = len(results)
        
        if results:
            self.logger.info(f"Sold {count} positions")
            
            # Update statistics
            for trade in results:
                profit_loss = trade.get('profit_loss', 0)
                self.profit_loss += profit_loss
                
                if profit_loss > 0:
                    self.win_count += 1
                else:
                    self.loss_count += 1
        
        return count
    
    def get_status(self):
        """Get current trading status"""
        # Get open orders count across all symbols
        open_orders_count = sum(len(orders) for orders in self.binance_client.open_orders.values())
        
        # Obter saldos atuais e formatar para exibição
        balances = self.binance_client.get_account_balance()
        
        # Forçar sincronização se for a primeira vez
        if self.last_update_time is None:
           self.min_order_usdt = getattr(self.config, "min_order_usdt", 12)
        self.min_signal_interval_minutes = self.config.get("min_signal_interval_minutes", 1)
        self.last_signal_time = {}  # {symbol: datetime}

        self.sync_needed = True
        self._sync_balances_with_open_orders()
        
        return {
            'running': self.running,
            'profit_loss': self.profit_loss,
            'win_count': self.win_count,
            'loss_count': self.loss_count,
            'open_positions': open_orders_count,
            'active_coins': self.binance_client.active_coins,
            'last_update': self.last_update_time,
            'balances': balances
        }
    
    def get_open_positions(self):
        """Get currently open positions for all symbols"""
        return self.binance_client.get_all_open_orders()
    
    def get_trades_history(self):
        """Get history of completed trades for all symbols"""
        return self.binance_client.get_trade_history()
    
    def get_historical_data(self, symbol=None):
        """Get recent historical data with indicators"""
        if symbol:
            return self.historical_data.get(symbol, pd.DataFrame())
        
        # Return the most recent data from any symbol
        if self.historical_data:
            # Find the symbol with the most recent data
            most_recent = None
            most_recent_time = None
            
            for symbol, data in self.historical_data.items():
                if not data.empty and (most_recent_time is None or data['timestamp'].iloc[-1] > most_recent_time):
                    most_recent = symbol
                    most_recent_time = data['timestamp'].iloc[-1]
            
            if most_recent:
                return self.historical_data[most_recent]
                
        return pd.DataFrame()
    
    def get_coin_analysis(self):
        """Get analysis data for all active coins"""
        return self.coin_analysis
    
    def _update_coin_selection(self):
        """Periodically update the active coins selection"""
        now = datetime.now()
        minutes_since_last = (now - self.last_coin_selection).total_seconds() / 60
        
        if minutes_since_last >= self.config.coin_selection_interval:
            self.logger.info(f"Updating coin selection after {minutes_since_last:.1f} minutes")
            self.binance_client.select_active_coins()
            self.last_coin_selection = now
    
    def _trading_loop(self):
        """Main trading loop"""
        self.logger.info("Starting trading loop")
        
        while self.running:
            try:
                # Check if we need to update coin selection
                self._update_coin_selection()
                
                # Sincronizar saldos periodicamente (a cada 5 minutos)
                self._sync_balances_with_open_orders()
                
                # Check status of all open orders
                self.binance_client.check_order_status()
                
                # For each active coin, run strategy
                for symbol in self.binance_client.active_coins:
                    # Update current price
                    price = self.binance_client.get_ticker_price(symbol)
                    if price:
                        self.current_prices[symbol] = price
                    
                    # Get historical data for analysis
                    klines = self.binance_client.get_historical_klines(
                        symbol=symbol,
                        interval=Client.KLINE_INTERVAL_1MINUTE, 
                        limit=100
                    )
                    
                    if klines.empty:
                        self.logger.warning(f"No historical data available for {symbol}")
                        continue
                    
                    # Apply strategy indicators
                    data_with_indicators = self.strategy.calculate_indicators(klines)
                    
                    # Store for dashboard
                    self.historical_data[symbol] = data_with_indicators
                    
                    # Check if in uptrend (if required)
                    is_uptrend = True
                    if self.config.uptrend_required:
                        is_uptrend = self.strategy.detect_uptrend(klines)
                    
                    # Store analysis results
                    self.coin_analysis[symbol] = {
                        'price': price,
                        'uptrend': is_uptrend,
                        'last_update': datetime.now()
                    }
                    
                    # Skip trading if not in uptrend and uptrend is required
                    if self.config.uptrend_required and not is_uptrend:
                        self.coin_analysis[symbol]['status'] = 'Waiting for uptrend'
                        self.coin_analysis[symbol]['signal'] = 'NONE'
                        continue
                    
                    # Check for buy signal
                    if self.strategy.should_buy(klines):
                        self.coin_analysis[symbol]['signal'] = 'BUY'
                        
                        # Place buy order
                        order = self.binance_client.place_buy_order(symbol)
                        if order:
                            self.logger.info(f"Buy order executed for {symbol}: {order['orderId']}")
                            self.coin_analysis[symbol]['status'] = 'Buy order placed'
                        else:
                            self.coin_analysis[symbol]['status'] = 'Buy signal - Order failed'
                    
                    # Check for sell signals from strategy
                    elif self.strategy.should_sell(klines):
                        self.coin_analysis[symbol]['signal'] = 'SELL'
                        self.coin_analysis[symbol]['status'] = 'Sell signal received'
                        self.logger.info(f"Strategy sell signal received for {symbol}")
                    else:
                        self.coin_analysis[symbol]['signal'] = 'NONE'
                        self.coin_analysis[symbol]['status'] = 'Monitoring'
                
                # Update performance metrics
                self._update_performance_metrics()
                
                # Update last update time
                self.last_update_time = datetime.now()
                
                # Sleep for the refresh interval
                time.sleep(self.config.refresh_interval)
                
            except Exception as e:
                self.logger.error(f"Error in trading loop: {e}")
                time.sleep(10)  # Sleep longer on error
        
        self.logger.info("Trading loop stopped")
    
    def _track_all_balances(self):
        """
        Rastreia todas as moedas com saldo e verifica se existem pares disponíveis
        para adicioná-los ao conjunto de moedas ativas para monitoramento
        """
        # Obter saldos atuais com cache
        balances = self.binance_client.get_account_balance()
        if not balances:
            return
            
        # Ignorar a moeda base (USDT)
        if self.config.quote_asset in balances:
            del balances[self.config.quote_asset]
        
        # Limitar o número de novas moedas a verificar por ciclo
        # para evitar sobrecarregar a API
        assets_to_check = list(balances.keys())
        
        # Manter uma lista de moedas já analisadas anteriormente
        if not hasattr(self, '_analyzed_assets'):
            self._analyzed_assets = []
        
        # Priorizar moedas ainda não analisadas
        unanalyzed_assets = [a for a in assets_to_check if a not in self._analyzed_assets]
        
        # Filtrar moedas que já estão sendo rastreadas
        active_symbols = self.binance_client.active_coins
        active_assets = [s[:-len(self.config.quote_asset)] for s in active_symbols]
        
        # Priorizar primeiro moedas não analisadas e não ativas
        priority_assets = [a for a in unanalyzed_assets if a not in active_assets]
        
        # Limitar a 3 moedas por ciclo para evitar sobrecarga
        if len(priority_assets) > 3:
            # Escolher 3 aleatoriamente, mas de forma determinística para cada ciclo
            seed = int(datetime.now().timestamp()) % 1000
            assets_to_process = priority_assets[:3]
        else:
            assets_to_process = priority_assets
            
            # Se ainda temos espaço, adicionar moedas não ativas já analisadas
            remaining_slots = 3 - len(assets_to_process)
            if remaining_slots > 0:
                analyzed_non_active = [a for a in self._analyzed_assets if a not in active_assets]
                assets_to_process.extend(analyzed_non_active[:remaining_slots])
        
        self.logger.debug(f"Processing {len(assets_to_process)} assets for balance tracking: {assets_to_process}")
            
        # Para cada moeda com saldo, verificar se existe um par com USDT
        for asset in assets_to_process:
            # Adicionar à lista de verificados
            if asset not in self._analyzed_assets:
                self._analyzed_assets.append(asset)
                
            balance_info = balances[asset]
            
            # Ignorar saldos muito pequenos (dust)
            if balance_info['free'] <= 0.000001:
                continue
                
            # Formar o símbolo completo
            symbol = f"{asset}{self.config.quote_asset}"
            
            # Verificar se é um par válido - usa cache internamente
            symbol_info = self.binance_client.get_symbol_info(symbol)
            if not symbol_info:
                continue  # Não é um par válido
                
            # Se não está nos active_coins e não está em open_orders, adicionar para monitoramento
            if (symbol not in self.binance_client.active_coins and 
                (symbol not in self.binance_client.open_orders or not self.binance_client.open_orders[symbol])):
                
                self.logger.info(f"Adding {symbol} to monitoring due to detected balance of {balance_info['free']} {asset}")
                
                # Adicionar o símbolo aos active_coins
                if symbol not in self.binance_client.active_coins:
                    self.binance_client.active_coins.append(symbol)
                    
                # Inicializar estruturas
                if symbol not in self.binance_client.open_orders:
                    self.binance_client.open_orders[symbol] = []
                    
                if symbol not in self.binance_client.trade_history:
                    self.binance_client.trade_history[symbol] = []
                    
                # Criar uma entrada no coin_analysis para que apareça no dashboard
                price = self.binance_client.get_ticker_price(symbol)  # Usa cache internamente
                self.coin_analysis[symbol] = {
                    'price': price,
                    'uptrend': True,  # Assumir como uptrend por padrão
                    'last_update': datetime.now(),
                    'status': 'Monitored - External balance',
                    'signal': 'NONE'
                }
    
    def _sync_balances_with_open_orders(self):
        """
        Sincroniza periodicamente os saldos com ordens abertas para evitar 
        inconsistências entre o que o robô acha que tem e o que realmente está na conta
        """
        now = datetime.now()
        minutes_since_last = (now - self.last_balance_sync).total_seconds() / 60
        
        # Executar a cada 5 minutos ou se sync_needed estiver marcado
        if minutes_since_last >= 5 or self.sync_needed:
            self.logger.info("Syncing balances with open positions and checking for ghost orders...")
            
            # Rastrear todas as moedas com saldos
            self._track_all_balances()
            
            # Selecionar apenas uma amostra de símbolos para checar a cada ciclo, para evitar sobrecarga
            # Para cada símbolo com ordens abertas, verificar ordens fantasmas
            symbols_to_check = list(self.binance_client.open_orders.keys())
            
            # Adicionar também símbolos ativos que podem não estar na lista de ordens abertas
            for symbol in self.binance_client.active_coins:
                if symbol not in symbols_to_check:
                    symbols_to_check.append(symbol)
            
            # Se temos muitos símbolos, limitar a quantidade para não sobrecarregar a API
            if len(symbols_to_check) > 5:
                # Escolher um subconjunto: todos com ordens abertas + alguns ativos
                open_order_symbols = list(self.binance_client.open_orders.keys())
                remaining_slots = max(0, 5 - len(open_order_symbols))
                
                # Adicionar primeiro todos os símbolos com ordens abertas
                batch_symbols = open_order_symbols.copy()
                
                # Se ainda há espaço, adicionar alguns outros ativos
                other_symbols = [s for s in symbols_to_check if s not in batch_symbols]
                if other_symbols and remaining_slots > 0:
                    # Rotacionar a lista para verificar símbolos diferentes a cada ciclo
                    start_idx = int(now.timestamp()) % len(other_symbols)
                    for i in range(min(remaining_slots, len(other_symbols))):
                        idx = (start_idx + i) % len(other_symbols)
                        batch_symbols.append(other_symbols[idx])
                
                symbols_to_check = batch_symbols
            
            self.logger.info(f"Checking ghost orders for {len(symbols_to_check)} symbols: {symbols_to_check}")
            
            # Verificar e corrigir ordens fantasmas para cada símbolo
            for symbol in symbols_to_check:
                # Usar a função específica para verificação de ordens fantasmas
                self.binance_client._check_and_fix_ghost_orders(symbol)
            
            # Atualizar tempo da última sincronização
            self.last_balance_sync = now
            self.sync_needed = False
                
    def _update_performance_metrics(self):
        """Update overall performance metrics"""
        # Get all trade history
        trades = self.binance_client.get_trade_history()
        
        # Reset counters
        total_pl_pct = 0
        wins = 0
        losses = 0
        
        # Count wins and losses
        for trade in trades:
            if trade['type'] == 'SELL':
                pl = trade.get('profit_loss', 0)
                if pl > 0:
                    wins += 1
                else:
                    losses += 1
                total_pl_pct += pl
        
        # Update tracking
        self.profit_loss = total_pl_pct
        self.win_count = wins
        self.loss_count = losses
        
        # Log performance data to arquivo
        self._log_performance_data(trades)
        
    def _log_performance_data(self, trades):
        """Registra dados de desempenho em arquivo para análise posterior"""
        try:
            # Dados de desempenho gerais
            perf_data = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'profit_loss_total': self.profit_loss,
                'win_count': self.win_count,
                'loss_count': self.loss_count,
                'total_trades': self.win_count + self.loss_count,
                'win_rate': (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0,
                'balance': self.binance_client.get_account_balance().get(self.config.quote_asset, {}).get('free', 0)
            }
            
            # Escrever no arquivo de performance
            with open(self.performance_log, 'a') as f:
                f.write(json.dumps(perf_data) + '\n')
                
            # Registrar trades recentes (últimos 10)
            recent_trades = [t for t in trades if t['type'] == 'SELL'][:10]
            
            if recent_trades:
                with open(self.trade_log, 'a') as f:
                    for trade in recent_trades:
                        # Verificar se este trade já foi registrado (usando order_id como chave)
                        trade_data = {
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'symbol': trade.get('symbol', 'UNKNOWN'),
                            'profit_loss': trade.get('profit_loss', 0),
                            'price': trade.get('price', 0),
                            'quantity': trade.get('quantity', 0),
                            'total': trade.get('total', 0),
                            'order_id': trade.get('order_id', 0),
                            'time': trade.get('time', datetime.now()).strftime('%Y-%m-%d %H:%M:%S') if isinstance(trade.get('time'), datetime) else str(trade.get('time'))
                        }
                        f.write(json.dumps(trade_data) + '\n')
                        
            self.logger.info(f"Performance log atualizado. Lucro total: {self.profit_loss:.2f}%, Win rate: {perf_data['win_rate']:.1f}%")
                
        except Exception as e:
            self.logger.error(f"Erro ao registrar dados de desempenho: {e}")