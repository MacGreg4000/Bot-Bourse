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


class BacktestEngine:
    """Moteur de backtesting qui rejoue la stratégie sur des données historiques."""

    def __init__(self, data_client: StockHistoricalDataClient,
                 initial_capital: float = 100_000.0,
                 max_position_pct: float = None,
                 stop_loss_pct: float = None,
                 take_profit_pct: float = None):
        self.data_client = data_client
        self.strategy = TradingStrategy(data_client)
        self.initial_capital = initial_capital
        self.max_position_pct = max_position_pct or Config.MAX_POSITION_SIZE_PERCENT
        self.stop_loss_pct = stop_loss_pct or Config.STOP_LOSS_PERCENT
        self.take_profit_pct = take_profit_pct or Config.TAKE_PROFIT_PERCENT

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

    def run(self, symbol: str, days: int = 365) -> dict:
        """Exécute le backtest pour un symbole sur N jours."""
        df = self.fetch_historical_data(symbol, days)
        if df.empty or len(df) < 50:
            return {'error': f'Pas assez de données pour {symbol}'}

        df = self.strategy.calculate_indicators(df)
        df = df.dropna()

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

            # Calcul de la valeur du portefeuille
            portfolio_value = cash + shares * price
            portfolio_values.append({'date': date, 'value': portfolio_value})

            # Vérifier stop-loss / take-profit si on a une position
            if shares > 0:
                change_pct = ((price - entry_price) / entry_price) * 100
                if change_pct <= -self.stop_loss_pct:
                    # Stop-loss déclenché
                    cash += shares * price
                    trades.append({
                        'date': date, 'symbol': symbol, 'action': 'SELL (SL)',
                        'price': price, 'qty': shares,
                        'pnl_pct': change_pct
                    })
                    shares = 0.0
                    entry_price = 0.0
                    continue
                elif change_pct >= self.take_profit_pct:
                    # Take-profit déclenché
                    cash += shares * price
                    trades.append({
                        'date': date, 'symbol': symbol, 'action': 'SELL (TP)',
                        'price': price, 'qty': shares,
                        'pnl_pct': change_pct
                    })
                    shares = 0.0
                    entry_price = 0.0
                    continue

            # Détection des signaux (même logique que generate_signals)
            ema_cross_up = (prev['EMA_9'] < prev['EMA_21']) and (current['EMA_9'] > current['EMA_21'])
            ema_cross_down = (prev['EMA_9'] > prev['EMA_21']) and (current['EMA_9'] < current['EMA_21'])
            high_volume = current['Volume'] > 1.5 * current['Volume_SMA']

            buy_signal = ema_cross_up and (50 < current['RSI'] < 75) and high_volume
            sell_signal = ema_cross_down or (current['RSI'] > 78)

            # Exécution
            if buy_signal and shares == 0:
                allocated = cash * (self.max_position_pct / 100.0)
                qty = allocated / price
                if qty > 0:
                    shares = qty
                    entry_price = price
                    cash -= shares * price
                    trades.append({
                        'date': date, 'symbol': symbol, 'action': 'BUY',
                        'price': price, 'qty': shares,
                        'pnl_pct': 0.0
                    })

            elif sell_signal and shares > 0:
                change_pct = ((price - entry_price) / entry_price) * 100
                cash += shares * price
                trades.append({
                    'date': date, 'symbol': symbol, 'action': 'SELL',
                    'price': price, 'qty': shares,
                    'pnl_pct': change_pct
                })
                shares = 0.0
                entry_price = 0.0

        # Valeur finale (clôturer la position ouverte)
        final_price = df.iloc[-1]['Close']
        final_value = cash + shares * final_price
        portfolio_df = pd.DataFrame(portfolio_values)

        # Calcul des métriques
        total_return_pct = ((final_value - self.initial_capital) / self.initial_capital) * 100
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

        # Buy & hold pour comparaison
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
