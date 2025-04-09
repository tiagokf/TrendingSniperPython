import dash
from dash import dcc, html, Input, Output, no_update
import dash_bootstrap_components as dbc
import logging
from datetime import datetime

class Dashboard:
    def __init__(self, config, trade_manager):
        self.config = config
        self.trade_manager = trade_manager
        self.logger = logging.getLogger("RoboCriptoCL.Dashboard")

        self.app = dash.Dash(
            __name__,
            external_stylesheets=[dbc.themes.DARKLY],
            title=f"RoboCriptoCL - {self.config.strategy.upper()} Bot",
            suppress_callback_exceptions=True
        )

        self._setup_layout()
        self._setup_callbacks()

    def start(self):
        self.logger.info(f"Starting dashboard on port {self.config.dashboard_port}")
        self.app.run(
            debug=False,
            port=self.config.dashboard_port,
            host="0.0.0.0",
            dev_tools_hot_reload=False,
            dev_tools_ui=False,
            dev_tools_props_check=False
        )

    def _setup_layout(self):
        # Coloca o dcc.Interval no topo para garantir que seja carregado imediatamente
        update_interval = dcc.Interval(id="update-interval", interval=5000, n_intervals=0)

        # Header
        header = dbc.Row(
            dbc.Col(
                html.H1(
                    f"RoboCriptoCL - {self.config.strategy.upper()} Bot",
                    className="text-center text-light my-4"
                ),
                width=12
            )
        )

        # Controle de bot
        controls = dbc.Row(
            [
                dbc.Col(dbc.Button("Start Bot", id="start-button", color="success", className="w-100"), width=4),
                dbc.Col(dbc.Button("Stop Bot", id="stop-button", color="danger", className="w-100"), width=4),
                dbc.Col(dbc.Button("Sell All", id="sell-button", color="warning", className="w-100"), width=4)
            ],
            className="mb-4"
        )

        # Card: Status & Wallet
        status_card = dbc.Card(
            [
                dbc.CardHeader(html.H4("Bot Status & Wallet", className="text-center")),
                dbc.CardBody(html.Div(id="status-content"))
            ],
            className="mb-4"
        )

        # Card: Trading Performance
        performance_card = dbc.Card(
            [
                dbc.CardHeader(html.H4("Trading Performance", className="text-center")),
                dbc.CardBody(html.Div(id="performance-content"))
            ],
            className="mb-4"
        )

        # Card: Open Positions
        positions_card = dbc.Card(
            [
                dbc.CardHeader(html.H4("Open Positions", className="text-center")),
                dbc.CardBody(html.Div(id="positions-content"))
            ],
            className="mb-4"
        )

        # Card: Active Coins
        coins_card = dbc.Card(
            [
                dbc.CardHeader(html.H4("Active Coins", className="text-center")),
                dbc.CardBody(html.Div(id="coins-content"))
            ],
            className="mb-4"
        )

        # Div oculta para o timestamp global (evitando conflito de IDs)
        hidden_timestamp = html.Div(id="global-update-time", style={"display": "none"})

        # Organiza o layout em duas linhas de cards
        self.app.layout = dbc.Container(
            [
                update_interval,
                header,
                controls,
                dbc.Row(
                    [
                        dbc.Col(status_card, width=6),
                        dbc.Col(performance_card, width=6)
                    ]
                ),
                dbc.Row(
                    [
                        dbc.Col(positions_card, width=6),
                        dbc.Col(coins_card, width=6)
                    ]
                ),
                hidden_timestamp
            ],
            fluid=True,
            style={
                "backgroundColor": "#222",
                "color": "#fff",
                "minHeight": "100vh",
                "padding": "20px"
            }
        )

    def _setup_callbacks(self):
        @self.app.callback(
            [Output("status-content", "children"),
             Output("global-update-time", "children")],
            [Input("update-interval", "n_intervals")]
        )
        def update_status(n):
            self.logger.info(f"Updating status: interval #{n}")
            status = self.trade_manager.get_status()
            timestamp = datetime.now().strftime("%H:%M:%S")

            # Log dos saldos para debug
            balances = status.get("balances", {})
            self.logger.info(f"Balances data: {balances}")

            # Configurado para 'quote asset' (ex: USDT)
            quote = self.config.quote_asset  # Ex: "USDT"
            # Tenta buscar o saldo do ativo de referência:
            balance_quote = balances.get(quote)
            if balance_quote:
                try:
                    free_quote = float(balance_quote.get("free", 0))
                    locked_quote = float(balance_quote.get("locked", 0))
                except Exception:
                    free_quote, locked_quote = 0.0, 0.0
            else:
                # Se não encontrar, emite aviso e usa 0
                self.logger.warning(f"Quote asset '{quote}' not found in balances. Available keys: {list(balances.keys())}")
                free_quote, locked_quote = 0.0, 0.0

            # Agora, calcula o valor total da conta convertendo cada moeda para o quote asset (ex: USDT)
            total_value = 0.0
            coins_with_balance = []
            analysis = self.trade_manager.get_coin_analysis() or {}
            # Função auxiliar para obter o preço de conversão:
            def get_price_for(coin):
                if coin == quote:
                    return 1.0
                pair = coin + quote
                try:
                    if pair in analysis:
                        return float(analysis[pair].get("price", 0))
                except Exception:
                    return None
                return None

            for coin, b in balances.items():
                try:
                    amount = float(b.get("free", 0)) + float(b.get("locked", 0))
                except Exception:
                    amount = 0.0
                if amount > 0:
                    price = get_price_for(coin)
                    if price:
                        value = amount * price
                        total_value += value
                        coins_with_balance.append(f"{coin}: {amount:.4f} ({value:.2f} {quote})")
                    else:
                        coins_with_balance.append(f"{coin}: {amount:.4f} (price N/A)")

            content = dbc.Container(
                [
                    dbc.Row(
                        [
                            dbc.Col(html.P("Bot Status:"), width="auto"),
                            dbc.Col(
                                html.Span(
                                    "Running" if status.get("running", False) else "Stopped",
                                    className="badge bg-success" if status.get("running", False) else "badge bg-danger"
                                ),
                                width="auto"
                            )
                        ],
                        align="center",
                        className="mb-2"
                    ),
                    dbc.Row(
                        dbc.Col(html.P(f"Total Account Value ({quote}): {total_value:.2f}"), width=12),
                        className="mb-1"
                    ),
                    dbc.Row(
                        dbc.Col(html.P("Coins with balance:", className="fw-bold"), width=12)
                    ),
                    dbc.Row(
                        dbc.Col(
                            html.Ul([html.Li(m) for m in coins_with_balance],
                                    style={"maxHeight": "200px", "overflowY": "auto"},
                                    className="small text-light"),
                            width=12
                        )
                    )
                ],
                fluid=True
            )

            update_time = html.P(f"Last update: {timestamp}", className="text-muted mt-3 mb-0 small")
            return content, update_time

        @self.app.callback(
            Output("performance-content", "children"),
            Input("update-interval", "n_intervals")
        )
        def update_performance(n):
            self.logger.info(f"Updating performance: interval #{n}")
            status = self.trade_manager.get_status()
            profit_loss = status.get("profit_loss", 0)
            win_count = status.get("win_count", 0)
            loss_count = status.get("loss_count", 0)
            total_trades = win_count + loss_count
            win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

            return dbc.Row(
                [
                    dbc.Col(
                        html.Div(
                            [
                                html.P("Total Profit/Loss:", className="mb-1"),
                                html.H3(f"{profit_loss:.2f}%", className="text-success" if profit_loss >= 0 else "text-danger")
                            ]
                        ),
                        width=4,
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                html.P("Win/Loss Ratio:", className="mb-1"),
                                html.H3(f"{win_count}/{loss_count}"),
                                html.P(f"Win Rate: {win_rate:.1f}%", className="small text-muted")
                            ]
                        ),
                        width=4,
                    ),
                    dbc.Col(
                        html.Div(
                            [
                                html.P("Active Coins:", className="mb-1"),
                                html.H3(f"{len(status.get('active_coins', []))}/{self.config.max_active_coins}"),
                                html.P(f"Open Positions: {status.get('open_positions', 0)}", className="small text-muted")
                            ]
                        ),
                        width=4,
                    ),
                ]
            )

        @self.app.callback(
            Output("positions-content", "children"),
            Input("update-interval", "n_intervals")
        )
        def update_positions(n):
            self.logger.info(f"Updating positions: interval #{n}")
            positions = self.trade_manager.get_open_positions()
            if not positions:
                return html.P("No open positions", className="text-muted fst-italic text-center py-3")

            header = html.Thead(html.Tr([
                html.Th("Symbol"), html.Th("Quantity"), html.Th("Entry Price"),
                html.Th("Current P/L"), html.Th("Target"), html.Th("Stop Loss"), html.Th("Time")
            ]))
            rows = []
            for pos in positions:
                symbol = pos.get("symbol", "N/A")
                pl = pos.get("profit_loss", 0)
                buy_time = pos.get("buy_time", datetime.now())
                if isinstance(buy_time, str):
                    try:
                        buy_time = datetime.strptime(buy_time, "%Y-%m-%d %H:%M:%S.%f")
                    except Exception:
                        try:
                            buy_time = datetime.strptime(buy_time, "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            buy_time = datetime.now()
                time_str = buy_time.strftime("%H:%M:%S")
                rows.append(html.Tr([
                    html.Td(symbol),
                    html.Td(f"{float(pos.get('executedQty', 0)):.6f}"),
                    html.Td(f"{pos.get('entry_price', 0):.6f}"),
                    html.Td(f"{pl:.2f}%", className="text-success" if pl >= 0 else "text-danger"),
                    html.Td(f"{pos.get('target_price', 0):.6f}"),
                    html.Td(f"{pos.get('stop_loss_price', 0):.6f}"),
                    html.Td(time_str)
                ]))
            return dbc.Table([header, html.Tbody(rows)], striped=True, hover=True, size="sm")

        @self.app.callback(
            Output("coins-content", "children"),
            Input("update-interval", "n_intervals")
        )
        def update_coins(n):
            self.logger.info(f"Updating coins: interval #{n}")
            status = self.trade_manager.get_status()
            active_coins = status.get("active_coins", [])
            if not active_coins:
                return html.P("No active coins", className="text-muted fst-italic text-center py-3")

            header = html.Thead(html.Tr([html.Th("Symbol"), html.Th("Price"), html.Th("Status")]))
            analysis = self.trade_manager.get_coin_analysis()
            rows = []
            for symbol in active_coins:
                data = analysis.get(symbol, {})
                price = data.get("price", "N/A")
                if isinstance(price, (int, float)):
                    price = f"{price:.8f}"
                else:
                    price = "N/A"
                rows.append(html.Tr([
                    html.Td(symbol),
                    html.Td(price),
                    html.Td(data.get("status", "Initializing"))
                ]))
            return dbc.Table([header, html.Tbody(rows)], striped=True, hover=True, size="sm")

        @self.app.callback(Output("start-button", "disabled"), Input("start-button", "n_clicks"))
        def on_start(n_clicks):
            if n_clicks:
                started = self.trade_manager.start()
                if started:
                    self.logger.info("Bot started successfully")
                    return True
            return no_update

        @self.app.callback(Output("stop-button", "disabled"), Input("stop-button", "n_clicks"))
        def on_stop(n_clicks):
            if n_clicks:
                stopped = self.trade_manager.stop()
                if stopped:
                    self.logger.info("Bot stopped successfully")
                    return True
            return no_update

        @self.app.callback(Output("sell-button", "disabled"), Input("sell-button", "n_clicks"))
        def on_sell_all(n_clicks):
            if n_clicks:
                self.trade_manager.sell_all()
            return no_update
