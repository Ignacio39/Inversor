import yfinance as yf
import requests
import pandas as pd


class CryptoBot:
    def fetch_market_data(self, symbol):
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="7d")
            if data.empty or len(data) < 7:
                return None
            current_price = data["Close"].iloc[-1]
            volume = data["Volume"].iloc[-1]
            sma_7 = data["Close"].rolling(window=7).mean().iloc[-1]
            return {
                "price": current_price,
                "volume": volume,
                "sma_7": sma_7
            }
        except Exception as e:
            print(f"Error fetching market data for {symbol}: {e}")
            return None

    def fetch_sentiment(self):
        try:
            response = requests.get("https://api.alternative.me/fng/", timeout=10)
            data = response.json()
            if data and "data" in data and len(data["data"]) > 0:
                latest = data["data"][0]
                return {
                    "value": int(latest["value"]),
                    "classification": latest["value_classification"]
                }
            return None
        except Exception as e:
            print(f"Error fetching sentiment: {e}")
            return None

    def evaluate_trade_signal(self, current_price, sma_7, fear_greed_value):
        if current_price > sma_7 and fear_greed_value <= 75:
            return 'BUY', 'Precio > SMA y Sentimiento aceptable'
        elif current_price < sma_7:
            return 'SELL', 'Precio por debajo de SMA (ruptura de tendencia)'
        else:
            return 'HOLD', 'Condiciones no cumplidas para entrar'


if __name__ == "__main__":
    bot = CryptoBot()

    print("=== Obteniendo datos de mercado (Bitcoin) ===")
    market_data = bot.fetch_market_data("BTC-USD")

    print("=== Obteniendo Fear & Greed Index ===")
    sentiment = bot.fetch_sentiment()

    senal, justificacion = bot.evaluate_trade_signal(
        market_data['price'], market_data['sma_7'], sentiment['value'] if sentiment else 50
    )

    print("\n--- Resumen ---")
    if market_data:
        print(f"Precio actual: ${market_data['price']:,.2f}")
        print(f"Volumen: {market_data['volume']:,.0f}")
        print(f"SMA 7 días: ${market_data['sma_7']:,.2f}")
    else:
        print("No se pudieron obtener los datos de mercado")

    if sentiment:
        print(f"Fear & Greed Index: {sentiment['value']} ({sentiment['classification']})")
    else:
        print("No se pudo obtener el índice de miedo y greed")

    print(f"\n--- Señal de Trading ---")
    print(f"Señal: {senal}")
    print(f"Justificación: {justificacion}")