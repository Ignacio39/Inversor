import time
from datetime import datetime
import yfinance as yf
import requests
import pandas as pd
from bot_core import CryptoBot


class LiveTradingBot(CryptoBot):
    def __init__(self):
        super().__init__()
        self.position_abierta = False
        self.symbol = "BTC-USD"

    def get_live_market_data(self, symbol=None):
        if symbol is None:
            symbol = self.symbol
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="60d")
            if data.empty or len(data) < 50:
                return None
            current_price = data["Close"].iloc[-1]
            sma_20 = data["Close"].rolling(window=20).mean().iloc[-1]
            sma_50 = data["Close"].rolling(window=50).mean().iloc[-1]
            return {
                "price": current_price,
                "sma_20": sma_20,
                "sma_50": sma_50,
            }
        except Exception as e:
            print(f"Error fetching live market data for {symbol}: {e}")
            return None

    def fetch_live_sentiment(self):
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
            print(f"Error fetching live sentiment: {e}")
            return None

    def run_live_trading_loop(self, check_interval=60):
        print("=" * 60)
        print("BOT DE TRADING EN VIVO - MONITOREO EN TIEMPO REAL")
        print("=" * 60)
        print(f"Símbolo: {self.symbol}")
        print(f"Posición inicial: {'ABIERTA' if self.position_abierta else 'CERRADA'}")
        print(f"Intervalo de revisión: {check_interval} segundos")
        print("Presiona Ctrl+C para detener el bot")
        print("=" * 60)

        try:
            while True:
                hora_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n--- Revisión #{hora_actual} ---")

                # Datos de mercado
                market_data = self.get_live_market_data()
                sentiment = self.fetch_live_sentiment()

                if market_data is None:
                    print("❌ No se pudieron obtener datos de mercado. Reintentando...")
                    time.sleep(check_interval)
                    continue

                price = market_data["price"]
                sma_20 = market_data["sma_20"]
                sma_50 = market_data["sma_50"]
                fg_value = sentiment["value"] if sentiment else 50
                fg_classification = sentiment["classification"] if sentiment else "Neutral"

                # Mostrar datos actuales
                print(f"Precio actual: ${price:,.2f}")
                print(f"SMA_20: ${sma_20:,.2f} | SMA_50: ${sma_50:,.2f}")
                print(f"Fear & Greed Index: {fg_value} ({fg_classification})")

                # Lógica de trading
                if not self.position_abierta:
                    # Condición de COMPRA: SMA_20 > SMA_50 Y Fear & Greed <= 75
                    if sma_20 > sma_50 and fg_value <= 75:
                        print("🚨 ALERTA GIGANTE: [COMPRA EJECUTADA] 🚨")
                        print(f"   - Precio (${price:,.2f}) > SMA_20 (${sma_20:,.2f}) y F&G <= 75")
                        print(f"   - Abriendo posición de compra en {self.symbol}")
                        self.position_abierta = True
                    else:
                        print("Mercado estable. Durmiendo...")
                else:
                    # Condición de VENTA: SMA_20 < SMA_50 (ruptura de tendencia)
                    if sma_20 < sma_50:
                        print("🚨 ALERTA GIGANTE: [VENTA EJECUTADA] 🚨")
                        print(f"   - Precio (${price:,.2f}) < SMA_20 (${sma_20:,.2f}) - Ruptura de tendencia")
                        print(f"   - Cerrando posición en {self.symbol}")
                        self.position_abierta = False
                    else:
                        print("Posición activa. Monitoreando tendencia...")
                        # También verificar si se mantiene la señal de compra
                        if sma_20 > sma_50 and fg_value <= 75:
                            print("   - Tendencia confirmada: SMA_20 aún > SMA_50 y sentimiento favorable")

                # Pausa antes de la siguiente revisión
                time.sleep(check_interval)

        except KeyboardInterrupt:
            print("\n" + "=" * 60)
            print("Bot detenido por el usuario")
            print(f"Posición final: {'ABIERTA' if self.position_abierta else 'CERRADA'}")
            print("=" * 60)


if __name__ == "__main__":
    bot = LiveTradingBot()
    bot.run_live_trading_loop(check_interval=60)