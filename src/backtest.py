import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from config import Config
from strategy import TradingStrategy
import logging

logger = logging.getLogger(__name__)


# Presets de stratégie
STRATEGY_PRESETS = {
    'Conservatrice (actuelle)': {
        'description': 'EMA crossover strict + RSI 50-75 + volume 1.5x — peu de trades, très sélectif',
        'ema_fast': 9, 'ema_slow': 21,
        'rsi_buy_min': 50, 'rsi_buy_max': 75,
        'rsi_sell': 78,
        'volume_mult': 1.5,
        'use_volume': True,
        'use_rsi_oversold': False, 'rsi_oversold': 30,
        'stop_loss': 5.0, 'take_profit': 10.0,
        'max_position_pct': 10.0,
    },
    'Agressive': {
        'description': 'EMA rapide + RSI large + pas de filtre volume — beaucoup plus de trades',
        'ema_fast': 5, 'ema_slow': 13,
        'rsi_buy_min': 35, 'rsi_buy_max': 70,
        'rsi_sell': 72,
        'volume_mult': 1.0,
        'use_volume': False,
        'use_rsi_oversold': True, 'rsi_oversold': 25,
        'stop_loss': 3.0, 'take_profit': 8.0,
        'max_position_pct': 20.0,
    },
    'Momentum': {
        'description': 'Suit la tendance forte — RSI élevé = force, pas de filtre volume',
        'ema_fast': 9, 'ema_slow': 21,
        'rsi_buy_min': 55, 'rsi_buy_max': 80,
        'rsi_sell': 85,
        'volume_mult': 1.0,
        'use_volume': False,
        'use_rsi_oversold': False, 'rsi_oversold': 30,
        'stop_loss': 7.0, 'take_profit': 15.0,
        'max_position_pct': 15.0,
    },
    'Mean Reversion': {
        'description': 'Achète les baisses (RSI oversold) et vend les rebonds',
        'ema_fast': 9, 'ema_slow': 21,
        'rsi_buy_min': 20, 'rsi_buy_max': 40,
        'rsi_sell': 65,
        'volume_mult': 1.0,
        'use_volume': False,
        'use_rsi_oversold': True, 'rsi_oversold': 30,
        'stop_loss': 4.0, 'take_profit': 8.0,
        'max_position_pct': 15.0,
    },
}


class StrategyParams:
    """Paramètres de stratégie configurables."""
    def __init__(self, ema_fast=9, ema_slow=21,
                 rsi_buy_min=50, rsi_buy_max=75, rsi_sell=78,
                 volume_mult=1.5, use_volume=True,
                 use_rsi_oversold=False, rsi_oversold=30,
                 stop_loss=5.0, take_profit=10.0,
                 max_position_pct=10.0):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_buy_min = rsi_buy_min
        self.rsi_buy_max = rsi_buy_max
        self.rsi_sell = rsi_sell
        self.volume_mult = volume_mult
        self.use_volume = use_volume
        self.use_rsi_oversold = use_rsi_oversold
        self.rsi_oversold = rsi_oversold
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.max_position_pct = max_position_pct

    @classmethod
    def from_preset(cls, preset_name):
        p = STRATEGY_PRESETS[preset_name]
        return cls(**{k: v for k, v in p.items() if k != 'description'})


class BacktestEngine:
    """Moteur de backtesting qui rejoue la stratégie sur des données historiques."""

    def __init__(self, data_client: StockHistoricalDataClient,
                 initial_capital: float = 100_000.0,
                 params: StrategyParams = None):
        self.data_client = data_client
        self.initial_capital = initial_capital
        self.params = params or StrategyParams()

    def fetch_historical_data(self, symbol: str, days: int = 365) -> pd.DataFrame:
        """Récupère les données historiques journalières sur N jours."""
        try:
            end = datetime.now()
            start = end - timedelta(days=days)
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
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
            logger.error(f"Erreur fetch historique {symbol}: {e}")
            return pd.DataFrame()

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcule les indicateurs avec les EMAs configurables."""
        import ta
        p = self.params
        df['EMA_fast'] = ta.trend.EMAIndicator(df['Close'], window=p.ema_fast).ema_indicator()
        df['EMA_slow'] = ta.trend.EMAIndicator(df['Close'], window=p.ema_slow).ema_indicator()
        df['RSI'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
        df['Volume_SMA'] = ta.trend.SMAIndicator(df['Volume'], window=20).sma_indicator()
        return df

    def run(self, symbol: str, days: int = 365) -> dict:
        """Exécute le backtest pour un symbole sur N jours."""
        df = self.fetch_historical_data(symbol, days)
        if df.empty or len(df) < 50:
            return {'error': f'Pas assez de données pour {symbol}'}

        df = self._calculate_indicators(df)
        df = df.dropna()

        p = self.params
        cash = self.initial_capital
        shares = 0.0
        entry_price = 0.0
        trades = []
        portfolio_values = []

        for i in range(1, len(df)):
            current = df.iloc[i]
            prev = df.iloc[i - 1]
            price = current['Close']
            date = df.index[i]

            portfolio_value = cash + shares * price
            portfolio_values.append({'date': date, 'value': portfolio_value})

            # Stop-loss / take-profit
            if shares > 0:
                change_pct = ((price - entry_price) / entry_price) * 100
                if change_pct <= -p.stop_loss:
                    cash += shares * price
                    trades.append({
                        'date': date, 'symbol': symbol, 'action': 'SELL (SL)',
                        'price': price, 'qty': shares, 'pnl_pct': change_pct
                    })
                    shares = 0.0
                    entry_price = 0.0
                    continue
                elif change_pct >= p.take_profit:
                    cash += shares * price
                    trades.append({
                        'date': date, 'symbol': symbol, 'action': 'SELL (TP)',
                        'price': price, 'qty': shares, 'pnl_pct': change_pct
                    })
                    shares = 0.0
                    entry_price = 0.0
                    continue

            # Signaux avec paramètres configurables
            ema_cross_up = (prev['EMA_fast'] < prev['EMA_slow']) and (current['EMA_fast'] > current['EMA_slow'])
            ema_cross_down = (prev['EMA_fast'] > prev['EMA_slow']) and (current['EMA_fast'] < current['EMA_slow'])

            # Signal d'achat : EMA crossover + RSI dans la zone configurée
            buy_signal = ema_cross_up and (p.rsi_buy_min < current['RSI'] < p.rsi_buy_max)

            # Filtre volume optionnel
            if p.use_volume and buy_signal:
                buy_signal = current['Volume'] > p.volume_mult * current['Volume_SMA']

            # Signal alternatif : RSI oversold (achat sur les creux)
            if p.use_rsi_oversold and not buy_signal and shares == 0:
                if current['RSI'] < p.rsi_oversold and current['EMA_fast'] > current['EMA_slow'] * 0.98:
                    buy_signal = True

            # Signal de vente
            sell_signal = ema_cross_down or (current['RSI'] > p.rsi_sell)

            # Exécution
            if buy_signal and shares == 0:
                allocated = cash * (p.max_position_pct / 100.0)
                qty = allocated / price
                if qty > 0:
                    shares = qty
                    entry_price = price
                    cash -= shares * price
                    trades.append({
                        'date': date, 'symbol': symbol, 'action': 'BUY',
                        'price': price, 'qty': shares, 'pnl_pct': 0.0
                    })

            elif sell_signal and shares > 0:
                change_pct = ((price - entry_price) / entry_price) * 100
                cash += shares * price
                trades.append({
                    'date': date, 'symbol': symbol, 'action': 'SELL',
                    'price': price, 'qty': shares, 'pnl_pct': change_pct
                })
                shares = 0.0
                entry_price = 0.0

        # Valeur finale
        final_price = df.iloc[-1]['Close']
        final_value = cash + shares * final_price
        portfolio_df = pd.DataFrame(portfolio_values)

        total_return_pct = ((final_value - self.initial_capital) / self.initial_capital) * 100
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
        buy_hold_return = ((df.iloc[-1]['Close'] - df.iloc[0]['Close']) / df.iloc[0]['Close']) * 100

        # Max drawdown
        max_drawdown = 0.0
        if not portfolio_df.empty:
            peak = portfolio_df['value'].expanding().max()
            drawdown = (portfolio_df['value'] - peak) / peak * 100
            max_drawdown = drawdown.min()

        # Stats des trades
        sell_trades = trades_df[trades_df['action'].str.startswith('SELL')] if not trades_df.empty else pd.DataFrame()
        win_trades = sell_trades[sell_trades['pnl_pct'] > 0] if not sell_trades.empty else pd.DataFrame()
        loss_trades = sell_trades[sell_trades['pnl_pct'] <= 0] if not sell_trades.empty else pd.DataFrame()

        nb_trades = len(sell_trades)
        win_rate = (len(win_trades) / nb_trades * 100) if nb_trades > 0 else 0
        avg_win = win_trades['pnl_pct'].mean() if not win_trades.empty else 0
        avg_loss = loss_trades['pnl_pct'].mean() if not loss_trades.empty else 0

        return {
            'symbol': symbol,
            'period_days': days,
            'initial_capital': self.initial_capital,
            'final_value': final_value,
            'total_return_pct': total_return_pct,
            'buy_hold_return_pct': buy_hold_return,
            'max_drawdown_pct': max_drawdown,
            'nb_trades': nb_trades,
            'win_rate': win_rate,
            'avg_win_pct': avg_win,
            'avg_loss_pct': avg_loss,
            'trades': trades_df,
            'portfolio': portfolio_df,
            'df': df,
            'open_position': shares > 0,
        }
