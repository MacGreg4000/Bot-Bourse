from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
from alpaca.data import StockHistoricalDataClient
from config import Config
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TradingEngine:
    def __init__(self, trading_client: TradingClient, data_client: StockHistoricalDataClient):
        self.trading_client = trading_client
        self.data_client = data_client
        self.last_api_call = 0
        self.min_interval = 1  # 1 seconde minimum entre appels API

    def _rate_limit(self):
        """Applique un rate limiting pour éviter les appels API excessifs"""
        elapsed = time.time() - self.last_api_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_api_call = time.time()

    def get_account_balance(self):
        self._rate_limit()
        try:
            account = self.trading_client.get_account()
            return float(account.cash)
        except Exception as e:
            logger.error("Failed to get account balance")
            raise

    def get_positions(self):
        self._rate_limit()
        try:
            positions = self.trading_client.get_all_positions()
            return {pos.symbol: pos for pos in positions}
        except Exception as e:
            logger.error("Failed to get positions")
            raise

    def calculate_position_size(self, balance: float, price: float, max_pct: float) -> float:
        """Calcule la quantité à acheter selon le solde, le prix et l'allocation max (0-100%)"""
        if price <= 0 or balance <= 0:
            return 0.0
        allocated = balance * (max_pct / 100.0)
        qty = allocated / price
        return round(qty, 6)

    def check_stop_loss_take_profit(self, entry_price: float, current_price: float) -> str:
        """Retourne 'stop_loss', 'take_profit' ou 'hold' selon les seuils configurés"""
        if entry_price <= 0:
            return 'hold'
        change_pct = ((current_price - entry_price) / entry_price) * 100
        if change_pct <= -Config.STOP_LOSS_PERCENT:
            return 'stop_loss'
        if change_pct >= Config.TAKE_PROFIT_PERCENT:
            return 'take_profit'
        return 'hold'

    def place_buy_order(self, symbol: str, qty: float):
        self._rate_limit()
        try:
            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                type=OrderType.MARKET,
                time_in_force=TimeInForce.GTC
            )
            order = self.trading_client.submit_order(order_request)
            logger.info(f"Buy order placed for {symbol}: qty={qty}")
            return order
        except Exception as e:
            logger.error("Failed to place buy order")
            raise

    def place_sell_order(self, symbol: str, qty: float):
        self._rate_limit()
        try:
            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                type=OrderType.MARKET,
                time_in_force=TimeInForce.GTC
            )
            order = self.trading_client.submit_order(order_request)
            logger.info(f"Sell order placed for {symbol}: qty={qty}")
            return order
        except Exception as e:
            logger.error("Failed to place sell order")
            raise

    def check_market_open(self):
        self._rate_limit()
        try:
            clock = self.trading_client.get_clock()
            return clock.is_open
        except Exception as e:
            logger.error("Failed to check market status")
            raise

    def get_current_price(self, symbol: str):
        self._rate_limit()
        try:
            from alpaca.data.requests import StockLatestTradeRequest
            request = StockLatestTradeRequest(symbol_or_symbols=symbol)
            trade = self.data_client.get_stock_latest_trade(request)
            return float(trade[symbol].price)
        except Exception as e:
            logger.error("Failed to get current price")
            raise