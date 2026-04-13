import pandas as pd
import ta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TradingStrategy:
    def __init__(self, data_client: StockHistoricalDataClient):
        self.data_client = data_client
        self.timeframe = self._parse_timeframe(Config.TIMEFRAME)

    def _parse_timeframe(self, tf_str: str):
        if 'Min' in tf_str:
            minutes = int(tf_str.replace('Min', ''))
            return TimeFrame(minutes, TimeFrameUnit.Minute)
        elif 'Hour' in tf_str:
            hours = int(tf_str.replace('Hour', ''))
            return TimeFrame(hours, TimeFrameUnit.Hour)
        elif 'Day' in tf_str:
            return TimeFrame.Day
        else:
            return TimeFrame.Minute

    def fetch_data(self, symbol: str, limit: int = 100):
        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=self.timeframe,
                limit=limit,
                feed='iex'
            )
            bars = self.data_client.get_stock_bars(request)
            df = bars.df
            df.reset_index(inplace=True)
            df.rename(columns={
                'timestamp': 'date', 'open': 'Open', 'high': 'High',
                'low': 'Low', 'close': 'Close', 'volume': 'Volume'
            }, inplace=True)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des données pour {symbol}: {e}")
            return pd.DataFrame()

    def calculate_indicators(self, df: pd.DataFrame):
        # EMAs pour le croisement (core de la stratégie)
        df['EMA_9'] = ta.trend.EMAIndicator(df['Close'], window=9).ema_indicator()
        df['EMA_21'] = ta.trend.EMAIndicator(df['Close'], window=21).ema_indicator()

        # EMA 50 conservée pour l'affichage du graphique
        df['EMA_50'] = ta.trend.EMAIndicator(df['Close'], window=50).ema_indicator()

        # RSI momentum
        df['RSI'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()

        # MACD conservé pour l'affichage
        macd = ta.trend.MACD(df['Close'])
        df['MACD'] = macd.macd()
        df['MACD_signal'] = macd.macd_signal()
        df['MACD_diff'] = macd.macd_diff()

        # Volume : moyenne mobile pour confirmer les signaux
        df['Volume_SMA'] = ta.trend.SMAIndicator(df['Volume'], window=20).sma_indicator()

        return df

    def generate_signals(self, df: pd.DataFrame) -> dict:
        if len(df) < 2:
            return {'buy': False, 'sell': False}

        prev = df.iloc[-2]
        latest = df.iloc[-1]

        # Détection du croisement EMA
        ema_cross_up = (prev['EMA_9'] < prev['EMA_21']) and (latest['EMA_9'] > latest['EMA_21'])
        ema_cross_down = (prev['EMA_9'] > prev['EMA_21']) and (latest['EMA_9'] < latest['EMA_21'])

        # Confirmation par le volume : volume actuel > 1.5x la moyenne
        high_volume = latest['Volume'] > 1.5 * latest['Volume_SMA']

        # ACHAT : croisement EMA haussier + RSI en zone momentum (50-75) + volume confirmé
        buy_signal = ema_cross_up and (50 < latest['RSI'] < 75) and high_volume

        # VENTE : croisement EMA baissier OU RSI en surachat extrême
        sell_signal = ema_cross_down or (latest['RSI'] > 78)

        return {'buy': bool(buy_signal), 'sell': bool(sell_signal)}
