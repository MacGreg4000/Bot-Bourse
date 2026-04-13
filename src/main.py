import os
import sys
import signal
import logging
import threading
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data import StockHistoricalDataClient
from config import Config
from engine import TradingEngine
from strategy import TradingStrategy

LOG_PATH = os.path.join(os.path.dirname(__file__), '..', 'logs', 'bot.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_PATH),
    ]
)
logger = logging.getLogger(__name__)

TIMEFRAME_SECONDS = {
    '1Min': 60,
    '5Min': 300,
    '15Min': 900,
    '1Hour': 3600,
    '1Day': 86400,
}

shutdown_event = threading.Event()


def handle_signal(signum, frame):
    logger.info(f"Signal {signum} reçu. Arrêt propre en cours...")
    shutdown_event.set()


def run_trading_loop(engine: TradingEngine, strategy: TradingStrategy):
    sleep_seconds = TIMEFRAME_SECONDS.get(Config.TIMEFRAME, 300)
    logger.info(f"Bot démarré | Symboles={Config.SYMBOLS} | Timeframe={Config.TIMEFRAME} | Paper={Config.PAPER_TRADING}")

    while not shutdown_event.is_set():
        try:
            # Vérifier que le marché est ouvert (NYSE : 9h30-16h00 ET, lun-ven)
            if not engine.check_market_open():
                logger.info("Marché fermé. Attente du prochain cycle.")
                shutdown_event.wait(sleep_seconds)
                continue

            for symbol in Config.SYMBOLS:
                if shutdown_event.is_set():
                    break
                try:
                    # 1. Récupérer les données et calculer les indicateurs
                    df = strategy.fetch_data(symbol, limit=100)
                    if df.empty:
                        logger.warning(f"[{symbol}] Aucune donnée reçue. Cycle ignoré.")
                        continue

                    df = strategy.calculate_indicators(df)
                    df.dropna(inplace=True)

                    if len(df) < 2:
                        logger.warning(f"[{symbol}] Pas assez de données après indicateurs. Cycle ignoré.")
                        continue

                    # 2. Générer les signaux
                    signals = strategy.generate_signals(df)
                    logger.info(f"[{symbol}] Signaux: achat={signals['buy']}, vente={signals['sell']}")

                    # 3. Récupérer l'état du compte
                    balance = engine.get_account_balance()
                    positions = engine.get_positions()
                    current_price = engine.get_current_price(symbol)

                    logger.info(f"[{symbol}] Solde: ${balance:.2f} | Prix actuel: ${current_price:.2f}")

                    # 4. Vérifier stop-loss / take-profit sur position existante
                    if symbol in positions:
                        pos = positions[symbol]
                        entry_price = float(pos.avg_entry_price)
                        action = engine.check_stop_loss_take_profit(entry_price, current_price)

                        if action == 'stop_loss':
                            logger.warning(f"[{symbol}] Stop-loss déclenché. Entrée={entry_price:.2f}, Actuel={current_price:.2f}")
                            engine.place_sell_order(symbol, float(pos.qty))
                            continue
                        elif action == 'take_profit':
                            logger.info(f"[{symbol}] Take-profit déclenché. Entrée={entry_price:.2f}, Actuel={current_price:.2f}")
                            engine.place_sell_order(symbol, float(pos.qty))
                            continue

                    # 5. Exécuter les signaux
                    if signals['buy'] and symbol not in positions:
                        qty = engine.calculate_position_size(balance, current_price, Config.MAX_POSITION_SIZE_PERCENT)
                        if qty > 0:
                            logger.info(f"[{symbol}] Signal ACHAT: qty={qty}, prix={current_price:.2f}")
                            engine.place_buy_order(symbol, qty)
                        else:
                            logger.warning(f"[{symbol}] Quantité calculée = 0. Vérifiez le solde et MAX_POSITION_SIZE_PERCENT.")

                    elif signals['sell'] and symbol in positions:
                        pos = positions[symbol]
                        logger.info(f"[{symbol}] Signal VENTE: qty={pos.qty}")
                        engine.place_sell_order(symbol, float(pos.qty))

                except Exception as e:
                    logger.error(f"[{symbol}] Erreur dans le cycle: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {e}", exc_info=True)

        shutdown_event.wait(sleep_seconds)

    logger.info("Bot arrêté proprement.")


def main():
    load_dotenv()

    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"Configuration invalide: {e}")
        sys.exit(1)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    trading_client = TradingClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY,
        paper=Config.PAPER_TRADING
    )
    data_client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    engine = TradingEngine(trading_client, data_client)
    strategy = TradingStrategy(data_client)

    run_trading_loop(engine, strategy)


if __name__ == "__main__":
    main()
