import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from config import Config
import ta
import logging

logger = logging.getLogger(__name__)


# Presets de stratégie
STRATEGY_PRESETS = {
    'Stay in Trend': {
        'description': 'Reste investi à 80% tant que prix > EMA — capte toute la hausse, sort quand la tendance casse',
        'mode': 'trend',
        'ema_trend': 21,
        'allocation_pct': 80.0,
        'trailing_stop': 10.0,
    },
    'Buy the Dips': {
        'description': 'Achète chaque creux RSI dans une tendance haussière — plusieurs entrées, vend sur rebond',
        'mode': 'dips',
        'ema_trend': 50,
        'rsi_buy': 35,
        'rsi_sell': 70,
        'buy_size_pct': 20.0,
        'max_invested_pct': 80.0,
    },
    'Trend Following': {
        'description': 'EMA crossover + trailing stop 8% — laisse courir les gains',
        'mode': 'crossover',
        'ema_fast': 9, 'ema_slow': 21,
        'rsi_buy_min': 40, 'rsi_buy_max': 85,
        'rsi_sell': 95,
        'use_volume': False, 'volume_mult': 1.0,
        'use_rsi_oversold': True, 'rsi_oversold': 35,
        'stop_loss': 5.0, 'take_profit': 0.0,
        'trailing_stop': 8.0, 'use_trailing_stop': True,
        'sell_on_ema_cross': True, 'sell_on_rsi': False,
        'max_position_pct': 30.0,
    },
    'Agressive': {
        'description': 'EMA rapide 5/13 + trailing stop 6% — réactif sur valeurs volatiles',
        'mode': 'crossover',
        'ema_fast': 5, 'ema_slow': 13,
        'rsi_buy_min': 35, 'rsi_buy_max': 70,
        'rsi_sell': 72,
        'use_volume': False, 'volume_mult': 1.0,
        'use_rsi_oversold': True, 'rsi_oversold': 25,
        'stop_loss': 4.0, 'take_profit': 0.0,
        'trailing_stop': 6.0, 'use_trailing_stop': True,
        'sell_on_ema_cross': True, 'sell_on_rsi': False,
        'max_position_pct': 25.0,
    },
    'Conservatrice (ancienne)': {
        'description': 'Stratégie originale — EMA 9/21 + RSI 50-75 + volume — quasi aucun trade',
        'mode': 'crossover',
        'ema_fast': 9, 'ema_slow': 21,
        'rsi_buy_min': 50, 'rsi_buy_max': 75,
        'rsi_sell': 78,
        'use_volume': True, 'volume_mult': 1.5,
        'use_rsi_oversold': False, 'rsi_oversold': 30,
        'stop_loss': 5.0, 'take_profit': 10.0,
        'trailing_stop': 0.0, 'use_trailing_stop': False,
        'sell_on_ema_cross': True, 'sell_on_rsi': True,
        'max_position_pct': 10.0,
    },
}


class BacktestEngine:
    """Moteur de backtesting multi-stratégie."""

    def __init__(self, data_client: StockHistoricalDataClient,
                 initial_capital: float = 100_000.0,
                 preset_name: str = 'Stay in Trend',
                 custom_params: dict = None):
        self.data_client = data_client
        self.initial_capital = initial_capital
        self.preset_name = preset_name
        self.params = dict(STRATEGY_PRESETS[preset_name])
        if custom_params:
            self.params.update(custom_params)

    def fetch_historical_data(self, symbol: str, days: int = 365) -> pd.DataFrame:
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
        df = self.fetch_historical_data(symbol, days)
        if df.empty or len(df) < 50:
            return {'error': f'Pas assez de données pour {symbol}'}

        mode = self.params.get('mode', 'crossover')
        if mode == 'trend':
            return self._run_stay_in_trend(symbol, df)
        elif mode == 'dips':
            return self._run_buy_dips(symbol, df)
        else:
            return self._run_crossover(symbol, df)

    def _compute_metrics(self, symbol, df, portfolio_values, trades, cash, shares):
        final_price = df.iloc[-1]['Close']
        final_value = cash + shares * final_price
        portfolio_df = pd.DataFrame(portfolio_values)

        total_return_pct = ((final_value - self.initial_capital) / self.initial_capital) * 100
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
        buy_hold_return = ((df.iloc[-1]['Close'] - df.iloc[0]['Close']) / df.iloc[0]['Close']) * 100

        max_drawdown = 0.0
        if not portfolio_df.empty:
            peak = portfolio_df['value'].expanding().max()
            drawdown = (portfolio_df['value'] - peak) / peak * 100
            max_drawdown = drawdown.min()

        sell_trades = trades_df[trades_df['action'].str.startswith('SELL')] if not trades_df.empty else pd.DataFrame()
        win_trades = sell_trades[sell_trades['pnl_pct'] > 0] if not sell_trades.empty else pd.DataFrame()
        loss_trades = sell_trades[sell_trades['pnl_pct'] <= 0] if not sell_trades.empty else pd.DataFrame()

        nb_trades = len(sell_trades)
        win_rate = (len(win_trades) / nb_trades * 100) if nb_trades > 0 else 0
        avg_win = win_trades['pnl_pct'].mean() if not win_trades.empty else 0
        avg_loss = loss_trades['pnl_pct'].mean() if not loss_trades.empty else 0

        return {
            'symbol': symbol,
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

    # ── Stay in Trend ──────────────────────────────────────────
    def _run_stay_in_trend(self, symbol, df):
        """Reste investi tant que prix > EMA, sort quand ça casse."""
        p = self.params
        ema_window = p.get('ema_trend', 21)
        alloc = p.get('allocation_pct', 80.0)
        ts_pct = p.get('trailing_stop', 10.0)

        df['EMA_trend'] = ta.trend.EMAIndicator(df['Close'], window=ema_window).ema_indicator()
        df = df.dropna()

        cash = self.initial_capital
        shares = 0.0
        entry_price = 0.0
        highest = 0.0
        trades = []
        portfolio_values = []

        for i in range(1, len(df)):
            price = df.iloc[i]['Close']
            date = df.index[i]
            ema = df.iloc[i]['EMA_trend']

            portfolio_value = cash + shares * price
            portfolio_values.append({'date': date, 'value': portfolio_value})

            if shares > 0:
                if price > highest:
                    highest = price
                change_pct = ((price - entry_price) / entry_price) * 100

                # Trailing stop
                if ts_pct > 0 and highest > 0:
                    drop = ((highest - price) / highest) * 100
                    if drop >= ts_pct:
                        cash += shares * price
                        trades.append({'date': date, 'symbol': symbol, 'action': 'SELL (TS)',
                                       'price': price, 'qty': shares, 'pnl_pct': change_pct})
                        shares = 0.0
                        entry_price = 0.0
                        highest = 0.0
                        continue

                # Sortie sur cassure EMA
                if price < ema:
                    cash += shares * price
                    trades.append({'date': date, 'symbol': symbol, 'action': 'SELL',
                                   'price': price, 'qty': shares, 'pnl_pct': change_pct})
                    shares = 0.0
                    entry_price = 0.0
                    highest = 0.0

            else:
                # Entrée quand prix repasse au-dessus de l'EMA
                if price > ema:
                    invest = (cash + shares * price) * (alloc / 100.0)
                    invest = min(invest, cash)
                    if invest > 0:
                        qty = invest / price
                        shares = qty
                        entry_price = price
                        highest = price
                        cash -= invest
                        trades.append({'date': date, 'symbol': symbol, 'action': 'BUY',
                                       'price': price, 'qty': qty, 'pnl_pct': 0.0})

        return self._compute_metrics(symbol, df, portfolio_values, trades, cash, shares)

    # ── Buy the Dips ───────────────────────────────────────────
    def _run_buy_dips(self, symbol, df):
        """Achète chaque creux RSI dans une tendance haussière."""
        p = self.params
        ema_window = p.get('ema_trend', 50)
        rsi_buy = p.get('rsi_buy', 35)
        rsi_sell = p.get('rsi_sell', 70)
        buy_size = p.get('buy_size_pct', 20.0)
        max_invested = p.get('max_invested_pct', 80.0)

        df['EMA_trend'] = ta.trend.EMAIndicator(df['Close'], window=ema_window).ema_indicator()
        df['RSI'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
        df = df.dropna()

        cash = self.initial_capital
        lots = []  # Liste de (qty, entry_price) pour chaque achat
        trades = []
        portfolio_values = []
        bought_this_dip = False  # Éviter d'acheter plusieurs fois dans le même creux

        for i in range(1, len(df)):
            price = df.iloc[i]['Close']
            prev_rsi = df.iloc[i - 1]['RSI']
            rsi = df.iloc[i]['RSI']
            date = df.index[i]
            ema = df.iloc[i]['EMA_trend']

            total_shares = sum(q for q, _ in lots)
            portfolio_value = cash + total_shares * price
            portfolio_values.append({'date': date, 'value': portfolio_value})

            invested_pct = (total_shares * price) / portfolio_value * 100 if portfolio_value > 0 else 0

            # Reset du flag quand le RSI remonte au-dessus du seuil d'achat
            if rsi > rsi_buy + 10:
                bought_this_dip = False

            # Achat sur creux RSI dans une tendance haussière
            if (rsi < rsi_buy and not bought_this_dip
                    and price > ema and invested_pct < max_invested):
                invest = portfolio_value * (buy_size / 100.0)
                invest = min(invest, cash)
                if invest > price:
                    qty = invest / price
                    lots.append((qty, price))
                    cash -= invest
                    bought_this_dip = True
                    trades.append({'date': date, 'symbol': symbol, 'action': 'BUY',
                                   'price': price, 'qty': qty, 'pnl_pct': 0.0})

            # Vente totale quand RSI > seuil de vente
            elif rsi > rsi_sell and lots:
                total_shares = sum(q for q, _ in lots)
                avg_entry = sum(q * ep for q, ep in lots) / total_shares
                pnl_pct = ((price - avg_entry) / avg_entry) * 100
                cash += total_shares * price
                trades.append({'date': date, 'symbol': symbol, 'action': 'SELL',
                               'price': price, 'qty': total_shares, 'pnl_pct': pnl_pct})
                lots = []
                bought_this_dip = False

            # Sortie de sécurité si tendance casse
            elif price < ema * 0.97 and lots:
                total_shares = sum(q for q, _ in lots)
                avg_entry = sum(q * ep for q, ep in lots) / total_shares
                pnl_pct = ((price - avg_entry) / avg_entry) * 100
                cash += total_shares * price
                trades.append({'date': date, 'symbol': symbol, 'action': 'SELL (EMA)',
                               'price': price, 'qty': total_shares, 'pnl_pct': pnl_pct})
                lots = []
                bought_this_dip = False

        total_shares = sum(q for q, _ in lots)
        return self._compute_metrics(symbol, df, portfolio_values, trades, cash, total_shares)

    # ── Crossover classique ────────────────────────────────────
    def _run_crossover(self, symbol, df):
        """Stratégie EMA crossover classique avec paramètres configurables."""
        p = self.params
        ema_fast_w = p.get('ema_fast', 9)
        ema_slow_w = p.get('ema_slow', 21)

        df['EMA_fast'] = ta.trend.EMAIndicator(df['Close'], window=ema_fast_w).ema_indicator()
        df['EMA_slow'] = ta.trend.EMAIndicator(df['Close'], window=ema_slow_w).ema_indicator()
        df['RSI'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
        df['Volume_SMA'] = ta.trend.SMAIndicator(df['Volume'], window=20).sma_indicator()
        df = df.dropna()

        cash = self.initial_capital
        shares = 0.0
        entry_price = 0.0
        highest = 0.0
        trades = []
        portfolio_values = []

        for i in range(1, len(df)):
            current = df.iloc[i]
            prev = df.iloc[i - 1]
            price = current['Close']
            date = df.index[i]

            portfolio_value = cash + shares * price
            portfolio_values.append({'date': date, 'value': portfolio_value})

            if shares > 0:
                if price > highest:
                    highest = price
                change_pct = ((price - entry_price) / entry_price) * 100

                # Trailing stop
                if p.get('use_trailing_stop') and p.get('trailing_stop', 0) > 0 and highest > 0:
                    drop = ((highest - price) / highest) * 100
                    if drop >= p['trailing_stop']:
                        cash += shares * price
                        trades.append({'date': date, 'symbol': symbol, 'action': 'SELL (TS)',
                                       'price': price, 'qty': shares, 'pnl_pct': change_pct})
                        shares = 0.0
                        entry_price = 0.0
                        highest = 0.0
                        continue

                # Stop-loss fixe
                if p.get('stop_loss', 0) > 0 and change_pct <= -p['stop_loss']:
                    cash += shares * price
                    trades.append({'date': date, 'symbol': symbol, 'action': 'SELL (SL)',
                                   'price': price, 'qty': shares, 'pnl_pct': change_pct})
                    shares = 0.0
                    entry_price = 0.0
                    highest = 0.0
                    continue

                # Take-profit fixe
                if p.get('take_profit', 0) > 0 and change_pct >= p['take_profit']:
                    cash += shares * price
                    trades.append({'date': date, 'symbol': symbol, 'action': 'SELL (TP)',
                                   'price': price, 'qty': shares, 'pnl_pct': change_pct})
                    shares = 0.0
                    entry_price = 0.0
                    highest = 0.0
                    continue

            # Signaux
            ema_cross_up = (prev['EMA_fast'] < prev['EMA_slow']) and (current['EMA_fast'] > current['EMA_slow'])
            ema_cross_down = (prev['EMA_fast'] > prev['EMA_slow']) and (current['EMA_fast'] < current['EMA_slow'])

            rsi_min = p.get('rsi_buy_min', 40)
            rsi_max = p.get('rsi_buy_max', 85)
            buy_signal = ema_cross_up and (rsi_min < current['RSI'] < rsi_max)

            if p.get('use_volume') and buy_signal:
                buy_signal = current['Volume'] > p.get('volume_mult', 1.5) * current['Volume_SMA']

            if p.get('use_rsi_oversold') and not buy_signal and shares == 0:
                if current['RSI'] < p.get('rsi_oversold', 35) and current['EMA_fast'] > current['EMA_slow'] * 0.98:
                    buy_signal = True

            sell_signal = False
            if p.get('sell_on_ema_cross') and ema_cross_down:
                sell_signal = True
            if p.get('sell_on_rsi') and current['RSI'] > p.get('rsi_sell', 78):
                sell_signal = True

            max_pos = p.get('max_position_pct', 30.0)
            if buy_signal and shares == 0:
                allocated = cash * (max_pos / 100.0)
                qty = allocated / price
                if qty > 0:
                    shares = qty
                    entry_price = price
                    highest = price
                    cash -= shares * price
                    trades.append({'date': date, 'symbol': symbol, 'action': 'BUY',
                                   'price': price, 'qty': shares, 'pnl_pct': 0.0})

            elif sell_signal and shares > 0:
                change_pct = ((price - entry_price) / entry_price) * 100
                cash += shares * price
                trades.append({'date': date, 'symbol': symbol, 'action': 'SELL',
                               'price': price, 'qty': shares, 'pnl_pct': change_pct})
                shares = 0.0
                entry_price = 0.0
                highest = 0.0

        return self._compute_metrics(symbol, df, portfolio_values, trades, cash, shares)
