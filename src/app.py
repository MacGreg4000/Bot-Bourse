import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from config import Config
from engine import TradingEngine
from strategy import TradingStrategy
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


def main():
    try:
        Config.validate()
    except ValueError as e:
        st.error(f"Configuration invalide : {e}")
        st.stop()

    st.set_page_config(page_title="Bot Trading Alpaca", page_icon="📈", layout="wide")
    st.title("🤖 Bot de Trading Algorithmique - Alpaca")
    st.markdown("**Interface de visualisation et contrôle**")

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
