import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from config import Config
from engine import TradingEngine
from strategy import TradingStrategy
from backtest import BacktestEngine, STRATEGY_PRESETS
from alpaca.trading.client import TradingClient
from alpaca.data import StockHistoricalDataClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialisation du cache par symbole
if 'data_cache' not in st.session_state:
    st.session_state.data_cache = {}  # clé = symbole


def update_data(symbol: str):
    """Met à jour les données depuis Alpaca pour un symbole donné."""
    try:
        trading_client = TradingClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY, paper=Config.PAPER_TRADING)
        data_client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)

        engine = TradingEngine(trading_client, data_client)
        strategy = TradingStrategy(data_client)

        df = strategy.fetch_data(symbol, limit=100)
        if not df.empty:
            df = strategy.calculate_indicators(df)
            signals = strategy.generate_signals(df)

            st.session_state.data_cache[symbol] = {
                'df': df,
                'signals': signals,
                'balance': engine.get_account_balance(),
                'positions': engine.get_positions(),
            }

        st.success(f"Données mises à jour pour {symbol} !")
    except Exception:
        st.error(f"Erreur lors de la mise à jour des données pour {symbol}")
        logger.error(f"Failed to update data for {symbol}", exc_info=True)


def _build_strategy_params(prefix: str, preset_name: str) -> dict:
    """Construit les paramètres depuis les widgets Streamlit selon le mode."""
    preset = STRATEGY_PRESETS[preset_name]
    mode = preset.get('mode', 'crossover')
    custom = {}

    with st.expander(f"Ajuster les paramètres ({prefix})", expanded=False):
        if mode == 'trend':
            col_a, col_b = st.columns(2)
            with col_a:
                custom['ema_trend'] = st.slider("EMA tendance", 10, 100, preset['ema_trend'], key=f"{prefix}_ema")
                custom['allocation_pct'] = st.slider("Allocation %", 20.0, 100.0, preset['allocation_pct'], 5.0, key=f"{prefix}_alloc",
                                                     help="% du capital investi quand la tendance est haussière")
            with col_b:
                custom['trailing_stop'] = st.slider("Trailing stop %", 0.0, 20.0, preset['trailing_stop'], 1.0, key=f"{prefix}_ts",
                                                    help="Vend si le prix chute de X% depuis son plus haut. 0 = désactivé")

        elif mode == 'dips':
            col_a, col_b = st.columns(2)
            with col_a:
                custom['ema_trend'] = st.slider("EMA tendance", 20, 100, preset['ema_trend'], key=f"{prefix}_ema")
                custom['rsi_buy'] = st.slider("RSI achat (creux)", 15, 45, preset['rsi_buy'], key=f"{prefix}_rsi_buy",
                                              help="Achète quand le RSI descend sous ce seuil")
                custom['rsi_sell'] = st.slider("RSI vente (rebond)", 55, 85, preset['rsi_sell'], key=f"{prefix}_rsi_sell",
                                              help="Vend quand le RSI remonte au-dessus")
            with col_b:
                custom['buy_size_pct'] = st.slider("Taille achat %", 10.0, 40.0, preset['buy_size_pct'], 5.0, key=f"{prefix}_size",
                                                   help="% du capital par achat de creux")
                custom['max_invested_pct'] = st.slider("Max investi %", 40.0, 100.0, preset['max_invested_pct'], 10.0, key=f"{prefix}_max",
                                                       help="Plafond d'investissement total")

        else:  # crossover
            st.markdown("**Signaux d'achat**")
            col_a, col_b = st.columns(2)
            with col_a:
                custom['ema_fast'] = st.slider("EMA rapide", 3, 20, preset['ema_fast'], key=f"{prefix}_ema_fast")
                custom['ema_slow'] = st.slider("EMA lente", 10, 50, preset['ema_slow'], key=f"{prefix}_ema_slow")
                custom['rsi_buy_min'] = st.slider("RSI achat min", 10, 80, preset['rsi_buy_min'], key=f"{prefix}_rsi_min")
                custom['rsi_buy_max'] = st.slider("RSI achat max", 50, 95, preset['rsi_buy_max'], key=f"{prefix}_rsi_max")
            with col_b:
                custom['use_rsi_oversold'] = st.checkbox("Achat RSI oversold", preset.get('use_rsi_oversold', False), key=f"{prefix}_use_os")
                if custom['use_rsi_oversold']:
                    custom['rsi_oversold'] = st.slider("Seuil RSI oversold", 15, 40, preset.get('rsi_oversold', 30), key=f"{prefix}_os")

            st.markdown("**Signaux de vente & risque**")
            col_c, col_d = st.columns(2)
            with col_c:
                custom['sell_on_ema_cross'] = st.checkbox("Vendre sur croisement EMA", preset.get('sell_on_ema_cross', True), key=f"{prefix}_sell_ema")
                custom['use_trailing_stop'] = st.checkbox("Trailing stop", preset.get('use_trailing_stop', False), key=f"{prefix}_use_ts")
                if custom['use_trailing_stop']:
                    custom['trailing_stop'] = st.slider("Trailing stop %", 3.0, 20.0, preset.get('trailing_stop', 8.0), 0.5, key=f"{prefix}_ts")
            with col_d:
                custom['stop_loss'] = st.slider("Stop-loss %", 0.0, 15.0, preset.get('stop_loss', 5.0), 0.5, key=f"{prefix}_sl")
                custom['take_profit'] = st.slider("Take-profit %", 0.0, 50.0, preset.get('take_profit', 0.0), 1.0, key=f"{prefix}_tp")
                custom['max_position_pct'] = st.slider("Taille position %", 5.0, 100.0, preset.get('max_position_pct', 30.0), 5.0, key=f"{prefix}_pos")

    return custom


def _run_backtest(data_client, symbols, days, capital, preset_name, custom_params, label):
    """Lance le backtest et retourne les résultats."""
    engine = BacktestEngine(data_client, initial_capital=float(capital),
                            preset_name=preset_name, custom_params=custom_params)
    results = []
    progress = st.progress(0, text=f"{label}...")
    for i, sym in enumerate(symbols):
        result = engine.run(sym, days=days)
        results.append(result)
        progress.progress((i + 1) / len(symbols), text=f"{label}: {sym}")
    progress.empty()
    return results


def _display_results(results, capital, label, color='blue'):
    """Affiche les résultats d'un backtest."""
    summary_rows = []
    for r in results:
        if 'error' in r:
            st.warning(r['error'])
            continue
        summary_rows.append({
            'Symbole': r['symbol'],
            'Rendement': f"{r['total_return_pct']:+.2f}%",
            'Buy & Hold': f"{r['buy_hold_return_pct']:+.2f}%",
            'Surperformance': f"{r['total_return_pct'] - r['buy_hold_return_pct']:+.2f}%",
            'Max Drawdown': f"{r['max_drawdown_pct']:.2f}%",
            'Trades': r['nb_trades'],
            'Win Rate': f"{r['win_rate']:.0f}%",
            'Gain Moy.': f"{r['avg_win_pct']:+.2f}%",
            'Perte Moy.': f"{r['avg_loss_pct']:+.2f}%",
            'Valeur Finale': f"${r['final_value']:,.2f}",
        })

    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    for r in results:
        if 'error' in r:
            continue

        st.markdown("---")
        st.subheader(f"{r['symbol']}")

        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Rendement", f"{r['total_return_pct']:+.2f}%")
        col_m2.metric("Buy & Hold", f"{r['buy_hold_return_pct']:+.2f}%")
        col_m3.metric("Max Drawdown", f"{r['max_drawdown_pct']:.2f}%")
        col_m4.metric("Win Rate", f"{r['win_rate']:.0f}% ({r['nb_trades']} trades)")

        portfolio_df = r['portfolio']
        df = r['df']
        trades_df = r['trades']

        if not portfolio_df.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                subplot_titles=('Prix & Trades', 'Valeur du Portefeuille'),
                                row_heights=[0.5, 0.5])

            fig.add_trace(go.Scatter(
                x=df.index, y=df['Close'], name="Prix",
                line=dict(color='gray', width=1)
            ), row=1, col=1)

            if not trades_df.empty:
                buys = trades_df[trades_df['action'] == 'BUY']
                sells = trades_df[trades_df['action'].str.startswith('SELL')]
                fig.add_trace(go.Scatter(
                    x=buys['date'], y=buys['price'], mode='markers',
                    name='Achat', marker=dict(color='green', size=10, symbol='triangle-up')
                ), row=1, col=1)
                fig.add_trace(go.Scatter(
                    x=sells['date'], y=sells['price'], mode='markers',
                    name='Vente', marker=dict(color='red', size=10, symbol='triangle-down')
                ), row=1, col=1)

            fig.add_trace(go.Scatter(
                x=portfolio_df['date'], y=portfolio_df['value'],
                name="Portefeuille", line=dict(color=color, width=2),
                fill='tozeroy', fillcolor=f'rgba(0,100,255,0.1)'
            ), row=2, col=1)

            fig.add_hline(y=float(capital), line_dash="dash", line_color="gray",
                          annotation_text="Capital initial", row=2, col=1)

            fig.update_layout(height=600, showlegend=True)
            st.plotly_chart(fig, use_container_width=True)

        if not trades_df.empty:
            with st.expander(f"Détail des {len(trades_df)} trades"):
                display_df = trades_df.copy()
                display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d')
                display_df['price'] = display_df['price'].map('${:,.2f}'.format)
                display_df['qty'] = display_df['qty'].map('{:.2f}'.format)
                display_df['pnl_pct'] = display_df['pnl_pct'].map('{:+.2f}%'.format)
                display_df.columns = ['Date', 'Symbole', 'Action', 'Prix', 'Quantité', 'P&L']
                st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_backtest_tab():
    """Onglet de backtesting historique."""
    st.header("📊 Backtest — Performance Historique")

    BACKTEST_SYMBOLS = ['AAPL', 'SPY', 'QQQ', 'TSLA', 'NVDA', 'MSFT', 'AMD', 'COIN', 'PLTR', 'MARA']

    # Paramètres généraux
    col1, col2, col3 = st.columns(3)
    with col1:
        symbols = st.multiselect("Symboles", BACKTEST_SYMBOLS, default=['TSLA', 'NVDA', 'SPY', 'AMD'])
    with col2:
        days = st.selectbox("Période", [90, 180, 365, 730], index=2,
                            format_func=lambda d: f"{d} jours ({d // 30} mois)")
    with col3:
        capital = st.number_input("Capital initial ($)", value=100_000, step=10_000, min_value=1_000)

    compare_mode = st.checkbox("Comparer deux stratégies", value=True)

    preset_names = list(STRATEGY_PRESETS.keys())

    if compare_mode:
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.subheader("Stratégie A")
            preset_a = st.selectbox("Preset", preset_names, index=0, key="preset_a")
            st.caption(STRATEGY_PRESETS[preset_a]['description'])
            custom_a = _build_strategy_params("a", preset_a)
        with col_s2:
            st.subheader("Stratégie B")
            preset_b = st.selectbox("Preset", preset_names, index=1, key="preset_b")
            st.caption(STRATEGY_PRESETS[preset_b]['description'])
            custom_b = _build_strategy_params("b", preset_b)
    else:
        preset_a = st.selectbox("Stratégie", preset_names, index=0)
        st.caption(STRATEGY_PRESETS[preset_a]['description'])
        custom_a = _build_strategy_params("single", preset_a)

    if st.button("🚀 Lancer le Backtest", type="primary"):
        if not symbols:
            st.warning("Sélectionnez au moins un symbole.")
            return

        data_client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)

        if compare_mode:
            results_a = _run_backtest(data_client, symbols, days, capital, preset_a, custom_a, "Stratégie A")
            results_b = _run_backtest(data_client, symbols, days, capital, preset_b, custom_b, "Stratégie B")

            # Tableau comparatif
            st.subheader("📋 Comparaison")
            compare_rows = []
            for ra, rb in zip(results_a, results_b):
                if 'error' in ra or 'error' in rb:
                    continue
                compare_rows.append({
                    'Symbole': ra['symbol'],
                    'A: Rendement': f"{ra['total_return_pct']:+.2f}%",
                    'B: Rendement': f"{rb['total_return_pct']:+.2f}%",
                    'Buy & Hold': f"{ra['buy_hold_return_pct']:+.2f}%",
                    'A: Trades': ra['nb_trades'],
                    'B: Trades': rb['nb_trades'],
                    'A: Win Rate': f"{ra['win_rate']:.0f}%",
                    'B: Win Rate': f"{rb['win_rate']:.0f}%",
                    'A: Drawdown': f"{ra['max_drawdown_pct']:.2f}%",
                    'B: Drawdown': f"{rb['max_drawdown_pct']:.2f}%",
                    'Meilleur': 'A' if ra['total_return_pct'] > rb['total_return_pct'] else 'B',
                })
            if compare_rows:
                st.dataframe(pd.DataFrame(compare_rows), use_container_width=True, hide_index=True)

            # Graphique comparatif des portefeuilles
            for ra, rb in zip(results_a, results_b):
                if 'error' in ra or 'error' in rb:
                    continue
                pa = ra['portfolio']
                pb = rb['portfolio']
                if pa.empty or pb.empty:
                    continue

                st.markdown("---")
                st.subheader(f"📈 {ra['symbol']} — Comparaison")

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=pa['date'], y=pa['value'],
                    name="Stratégie A", line=dict(color='dodgerblue', width=2)
                ))
                fig.add_trace(go.Scatter(
                    x=pb['date'], y=pb['value'],
                    name="Stratégie B", line=dict(color='orange', width=2)
                ))
                fig.add_hline(y=float(capital), line_dash="dash", line_color="gray",
                              annotation_text="Capital initial")
                fig.update_layout(
                    height=400, yaxis_title="Valeur ($)",
                    title=f"{ra['symbol']}: A ({ra['total_return_pct']:+.2f}%) vs B ({rb['total_return_pct']:+.2f}%)"
                )
                st.plotly_chart(fig, use_container_width=True)

            # Détails par stratégie
            tab_a, tab_b = st.tabs(["Détails Stratégie A", "Détails Stratégie B"])
            with tab_a:
                _display_results(results_a, capital, "A", color='dodgerblue')
            with tab_b:
                _display_results(results_b, capital, "B", color='orange')

        else:
            results = _run_backtest(data_client, symbols, days, capital, preset_a, custom_a, "Backtest")
            st.subheader("📋 Résultats")
            _display_results(results, capital, "Backtest")


def main():
    try:
        Config.validate()
    except ValueError as e:
        st.error(f"Configuration invalide : {e}")
        st.stop()

    st.set_page_config(page_title="Bot Trading Alpaca", page_icon="📈", layout="wide")
    st.title("🤖 Bot de Trading Algorithmique - Alpaca")

    tab_trading, tab_backtest = st.tabs(["📈 Trading", "📊 Backtest"])

    with tab_backtest:
        render_backtest_tab()

    with tab_trading:
        render_trading_tab()


def render_trading_tab():
    """Onglet principal de trading en temps réel."""
    with st.sidebar:
        st.header("⚙️ Contrôles")

        # Sélecteur de symbole
        selected_symbol = st.selectbox("Symbole", Config.SYMBOLS)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Actualiser", type="primary"):
                update_data(selected_symbol)
        with col2:
            cache = st.session_state.data_cache.get(selected_symbol, {})
            if st.button("📊 Analyser"):
                df = cache.get('df', pd.DataFrame())
                if not df.empty:
                    signals = cache.get('signals', {})
                    st.info(f"Signaux : Achat={signals.get('buy', False)}, Vente={signals.get('sell', False)}")
                else:
                    st.warning("Actualisez d'abord les données")

        st.markdown("---")
        st.markdown(f"**Mode:** {'📝 Paper' if Config.PAPER_TRADING else '💰 Live'}")
        st.markdown(f"**Symbole sélectionné:** {selected_symbol}")
        st.markdown(f"**Timeframe:** {Config.TIMEFRAME}")

        cache = st.session_state.data_cache.get(selected_symbol, {})
        balance = cache.get('balance', 0.0)
        signals = cache.get('signals', {})

        if balance > 0:
            st.metric("Solde", f"${balance:.2f}")

        # Bouton d'exécution — visible uniquement si un signal actif existe
        if signals.get('buy') or signals.get('sell'):
            st.markdown("---")
            st.subheader("Exécution")
            if signals.get('buy'):
                if st.button("Execute BUY", type="primary"):
                    try:
                        trading_client = TradingClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY, paper=Config.PAPER_TRADING)
                        data_client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)
                        engine = TradingEngine(trading_client, data_client)
                        price = engine.get_current_price(selected_symbol)
                        qty = engine.calculate_position_size(balance, price, Config.MAX_POSITION_SIZE_PERCENT)
                        if qty > 0:
                            engine.place_buy_order(selected_symbol, qty)
                            st.success(f"Ordre ACHAT placé : {qty} {selected_symbol} @ ~${price:.2f}")
                        else:
                            st.warning("Quantité calculée = 0. Vérifiez le solde.")
                    except Exception:
                        st.error("Erreur lors du placement de l'ordre")
                        logger.error("Execute BUY échoué", exc_info=True)

            elif signals.get('sell'):
                if st.button("Execute SELL", type="primary"):
                    try:
                        trading_client = TradingClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY, paper=Config.PAPER_TRADING)
                        data_client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)
                        engine = TradingEngine(trading_client, data_client)
                        positions = engine.get_positions()
                        if selected_symbol in positions:
                            qty = float(positions[selected_symbol].qty)
                            engine.place_sell_order(selected_symbol, qty)
                            st.success(f"Ordre VENTE placé : {qty} {selected_symbol}")
                        else:
                            st.warning("Aucune position ouverte à vendre.")
                    except Exception:
                        st.error("Erreur lors du placement de l'ordre")
                        logger.error("Execute SELL échoué", exc_info=True)

    # Contenu principal
    col1, col2 = st.columns([2, 1])

    with col1:
        st.header(f"📊 Graphique des Prix & Indicateurs — {selected_symbol}")

        cache = st.session_state.data_cache.get(selected_symbol, {})
        df = cache.get('df', pd.DataFrame())

        if not df.empty:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                                subplot_titles=('Prix & EMAs', 'RSI', 'MACD'),
                                row_heights=[0.5, 0.25, 0.25])

            # Bougies japonaises
            fig.add_trace(go.Candlestick(
                x=df.index, open=df['Open'], high=df['High'],
                low=df['Low'], close=df['Close'], name="Prix"
            ), row=1, col=1)

            # EMAs — les deux lignes de croisement + tendance long terme
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_9'], name="EMA 9",
                                     line=dict(color='green', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_21'], name="EMA 21",
                                     line=dict(color='blue', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], name="EMA 50",
                                     line=dict(color='orange', width=1)), row=1, col=1)

            # RSI avec seuils de la stratégie
            fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], name="RSI",
                                     line=dict(color='purple')), row=2, col=1)
            fig.add_hline(y=78, line_dash="dash", line_color="red", row=2, col=1)
            fig.add_hline(y=75, line_dash="dot", line_color="orange", row=2, col=1)
            fig.add_hline(y=50, line_dash="dash", line_color="gray", row=2, col=1)

            # MACD
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], name="MACD",
                                     line=dict(color='blue')), row=3, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=df['MACD_signal'], name="Signal",
                                     line=dict(color='red')), row=3, col=1)

            fig.update_layout(height=800, showlegend=True)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Cliquez sur 'Actualiser' pour charger les données et voir les graphiques.")

    with col2:
        st.header("📈 Signaux & Positions")

        cache = st.session_state.data_cache.get(selected_symbol, {})
        signals = cache.get('signals', {})
        positions = cache.get('positions', {})

        if signals:
            if signals.get('buy'):
                st.success("🟢 SIGNAL ACHAT")
            elif signals.get('sell'):
                st.error("🔴 SIGNAL VENTE")
            else:
                st.info("⏸️ AUCUN SIGNAL")
        else:
            st.info("⏸️ AUCUN SIGNAL")

        st.markdown("---")

        # Toutes les positions ouvertes
        if positions:
            for sym, pos in positions.items():
                st.metric(f"Position {sym}",
                          f"{pos.qty} @ ${float(pos.avg_entry_price):.2f}",
                          f"{float(pos.unrealized_pl):.2f}")
        else:
            st.info("Aucune position ouverte")

        st.markdown("---")
        st.subheader("ℹ️ Stratégie")
        st.write("**EMA Crossover + RSI + Volume**")
        st.write("**Achat :** EMA 9 croise EMA 21 haussier + RSI 50-75 + volume > 1.5x SMA")
        st.write("**Vente :** EMA 9 croise EMA 21 baissier OU RSI > 78")
        st.write("**Stop-loss :** −5% | **Take-profit :** +10%")

        st.markdown("---")
        st.subheader("📋 Liste des symboles suivis")
        for sym in Config.SYMBOLS:
            sym_cache = st.session_state.data_cache.get(sym, {})
            sym_signals = sym_cache.get('signals', {})
            if sym_signals.get('buy'):
                st.markdown(f"- **{sym}** 🟢")
            elif sym_signals.get('sell'):
                st.markdown(f"- **{sym}** 🔴")
            else:
                st.markdown(f"- {sym}")


if __name__ == "__main__":
    main()
