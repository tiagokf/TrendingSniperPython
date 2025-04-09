import os
import sys
import logging
import math
from pathlib import Path

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Import project modules
from src.utils.config import Config
from src.api.binance_client import BinanceClient
from src.strategies.scalping_strategy import ScalpingStrategy
from src.strategies.trend_sniper_strategy import TrendSniperStrategy
from src.utils.trade_manager import TradeManager
from src.dashboard.app import Dashboard

def main():
    """
    Main entry point for the RoboCriptoCL trading system
    """
    logger = logging.getLogger('RoboCriptoCL')
    if not logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
    logger.info("Starting RoboCriptoCL Bot")

    try:
        config = Config()
        logger.info("Configuration loaded successfully")

        if not config.api_key or not config.api_secret:
            logger.error("API keys not configured.")
            print("ERROR: API keys not configured.")
            sys.exit(1)

        logger.info("Initializing trading system")

        try:
            binance_client = BinanceClient(config)
        except Exception as e:
            logger.error(f"Failed to initialize Binance client: {e}")
            print(f"ERROR: Failed to initialize Binance client: {e}")
            sys.exit(1)

        # Escolha da estratégia com base na variável STRATEGY do .env
        strategy_name = os.getenv("STRATEGY", "scalping").lower()
        if strategy_name == "scalping":
            strategy = ScalpingStrategy(config)
            logger.info("Using ScalpingStrategy")
        elif strategy_name == "sniper":
            strategy = TrendSniperStrategy(config)
            logger.info("Using TrendSniperStrategy")
        else:
            logger.error(f"Estrategia desconhecida: {strategy_name}")
            print(f"ERROR: Estratégia desconhecida: {strategy_name}")
            sys.exit(1)

        trade_manager = TradeManager(config, binance_client, strategy)
        dashboard = Dashboard(config, trade_manager)

        dashboard.start()

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        print(f"ERROR: Unhandled exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
