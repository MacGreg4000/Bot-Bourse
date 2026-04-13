import os
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

class Config:
    ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
    ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY')
    PAPER_TRADING = os.getenv('PAPER_TRADING', 'TRUE').lower() == 'true'
    SYMBOLS = [s.strip().upper() for s in os.getenv('SYMBOLS', 'AAPL,SPY,QQQ').split(',')]
    TIMEFRAME = os.getenv('TIMEFRAME', '5Min')

    # Paramètres de risque
    STOP_LOSS_PERCENT = float(os.getenv('STOP_LOSS_PERCENT', '5.0'))
    TAKE_PROFIT_PERCENT = float(os.getenv('TAKE_PROFIT_PERCENT', '10.0'))
    MAX_POSITION_SIZE_PERCENT = float(os.getenv('MAX_POSITION_SIZE_PERCENT', '10.0'))

    @classmethod
    def validate(cls):
        if not cls.ALPACA_API_KEY or not cls.ALPACA_SECRET_KEY:
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env")

        if cls.STOP_LOSS_PERCENT < 0 or cls.STOP_LOSS_PERCENT > 100:
            raise ValueError("STOP_LOSS_PERCENT must be between 0 and 100")

        if cls.TAKE_PROFIT_PERCENT < 0 or cls.TAKE_PROFIT_PERCENT > 100:
            raise ValueError("TAKE_PROFIT_PERCENT must be between 0 and 100")

        if cls.MAX_POSITION_SIZE_PERCENT < 0 or cls.MAX_POSITION_SIZE_PERCENT > 100:
            raise ValueError("MAX_POSITION_SIZE_PERCENT must be between 0 and 100")

        if not cls.SYMBOLS:
            raise ValueError("SYMBOLS doit contenir au moins un ticker")
        for sym in cls.SYMBOLS:
            if not sym or not sym.isalpha():
                raise ValueError(f"Symbole invalide '{sym}' : doit être alphabétique (ex: 'AAPL', 'TSLA')")

        valid_timeframes = ['1Min', '5Min', '15Min', '1Hour', '1Day']
        if cls.TIMEFRAME not in valid_timeframes:
            raise ValueError(f"TIMEFRAME must be one of: {', '.join(valid_timeframes)}")

        return True
