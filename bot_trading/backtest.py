import yfinance as yf
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def fetch_market_data_history(symbol, days=730):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period=f"{days}d")
        if data.empty:
            return None
        data = data[['Close']].reset_index()
        data['Date'] = data['Date'].dt.date
        return data
    except Exception as e:
        print(f"Error fetching market history: {e}")
        return None


def fetch_sentiment_history(days=730):
    try:
        url = f"https://api.alternative.me/fng/?limit={days}"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data and "data" in data:
            records = []
            for entry in data["data"]:
                try:
                    ts = int(entry["timestamp"])
                    date_obj = pd.to_datetime(ts, unit='s').date()
                    value = int(entry["value"])
                    records.append({
                        "Date": date_obj,
                        "fear_greed_value": value
                    })
                except (ValueError, KeyError):
                    continue
            if records:
                df = pd.DataFrame(records)
                df = df.sort_values("Date").set_index("Date")
                return df
        return None
    except Exception as e:
        print(f"Error fetching sentiment history: {e}")
        return None


def run_backtest(initial_capital=10000, days=730):
    print("=" * 60)
    print("FASE 3 OPTIMIZED: BACKTESTING - SMA CROSSOVER STRATEGY")
    print("=" * 60)

    # Step 1: Data extraction
    print("\n[1/5] Descargando datos históricos de BTC-USD (2 años)...")
    market_data = fetch_market_data_history("BTC-USD", days)
    if market_data is None:
        print("ERROR: No se pudieron obtener los datos de mercado.")
        return

    print("[2/5] Descargando historial del Fear & Greed Index...")
    sentiment_data = fetch_sentiment_history(days)

    # Step 2: Data processing - calculate SMAs and merge
    print("[3/5] Calculando SMAs (20 y 50 días) y fusionando datos...")
    market_df = pd.DataFrame(market_data)
    market_df['Date'] = pd.to_datetime(market_df['Date']).dt.date

    # Calculate SMA_20 and SMA_50
    market_df['SMA_20'] = market_df['Close'].rolling(window=20).mean()
    market_df['SMA_50'] = market_df['Close'].rolling(window=50).mean()

    # Set Date as index
    market_df['Date'] = pd.to_datetime(market_df['Date'])
    market_df = market_df.set_index('Date')

    # Sort by date
    market_df = market_df.sort_index()

    # Merge sentiment data - align by date index
    if sentiment_data is not None and len(sentiment_data) > 0:
        merged = market_df.join(sentiment_data, how='left')
        sentiment_dates_covered = len(sentiment_data)
    else:
        merged = market_df.copy()
        merged['fear_greed_value'] = 50
        sentiment_dates_covered = 0

    # Fill missing fear & greed with ffill
    merged['fear_greed_value'] = merged['fear_greed_value'].ffill().fillna(50)

    # Step 3: Simulation engine
    print("[4/5] Ejecutando simulación de cartera día a día...")
    capital = initial_capital
    btc_held = 0.0
    in_market = False
    total_operations = 0
    buy_count = 0
    sell_count = 0
    commission = 0.0015  # 0.15%

    # Historial de operaciones para reporte y CSV
    trades_history = []

    merged = merged.sort_index()

    for date, row in merged.iterrows():
        close_price = row["Close"]
        sma_20 = row["SMA_20"]
        sma_50 = row["SMA_50"]
        fg_value = row["fear_greed_value"]

        # Skip rows where SMA values are NaN (not enough data for window)
        if pd.isna(sma_20) or pd.isna(sma_50):
            continue

        if not in_market:
            # Logic: BUY if SMA_20 > SMA_50 AND fear & greed <= 75
            if sma_20 > sma_50 and fg_value <= 75:
                # Buy: invest all capital in BTC after commission
                purchase_amount = capital * (1 - commission)
                btc_held = purchase_amount / close_price
                capital = 0.0
                in_market = True
                total_operations += 1
                buy_count += 1
                # Registrar operación de COMPRA
                trades_history.append({
                    "Fecha": date,
                    "Señal": "BUY",
                    "Precio_Ejecucion": close_price,
                    "Capital_Restante": capital,
                    "BTC_Adquirido": btc_held
                })
        else:
            # Logic: SELL if SMA_20 < SMA_50
            if sma_20 < sma_50:
                # Sell: convert all BTC to USD after commission
                sale_amount = btc_held * close_price * (1 - commission)
                capital = sale_amount
                btc_held = 0.0
                in_market = False
                total_operations += 1
                sell_count += 1
                # Registrar operación de VENTA
                trades_history.append({
                    "Fecha": date,
                    "Señal": "SELL",
                    "Precio_Ejecucion": close_price,
                    "Capital_Restante": capital,
                    "BTC_Adquirido": btc_held
                })

    # Calculate final results
    final_capital = capital if not in_market else btc_held * merged.iloc[-1]["Close"]

    total_return_pct = ((final_capital - initial_capital) / initial_capital) * 100

    # Export trades history to CSV
    trades_df = pd.DataFrame(trades_history)
    if len(trades_df) > 0:
        trades_df.to_csv("trades_history.csv", index=False)
        print(f"\nHistorial de {len(trades_df)} operaciones guardado en 'trades_history.csv'")

    # Step 5: Visualización Gráfica
    print("[5/5] Generando gráfico de resultados...")
    plt.figure(figsize=(14, 7))

    # Graficar precio de cierre y SMAs
    plt.plot(merged.index, merged["Close"], label="Precio Cierre BTC", color="blue", alpha=0.6)
    plt.plot(merged.index, merged["SMA_20"], label="SMA_20", color="orange", alpha=0.8)
    plt.plot(merged.index, merged["SMA_50"], label="SMA_50", color="green", alpha=0.8)

    # Marcar puntos de COMPRA (triángulos verdes arriba)
    buy_dates = []
    buy_prices = []
    for t in trades_history:
        if t["Señal"] == "BUY":
            buy_dates.append(t["Fecha"])
            buy_prices.append(t["Precio_Ejecucion"])
    if buy_dates:
        plt.scatter(buy_dates, buy_prices, marker="^", color="green", s=100, label="Compra", zorder=5)

    # Marcar puntos de VENTA (triángulos rojos abajo)
    sell_dates = []
    sell_prices = []
    for t in trades_history:
        if t["Señal"] == "SELL":
            sell_dates.append(t["Fecha"])
            sell_prices.append(t["Precio_Ejecucion"])
    if sell_dates:
        plt.scatter(sell_dates, sell_prices, marker="v", color="red", s=100, label="Venta", zorder=5)

    # Formato del gráfico
    plt.title("Backtesting Estrategia SMA Crossover - BTC-USD (2 Años)")
    plt.xlabel("Fecha")
    plt.ylabel("Precio (USD)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # Guardar gráfico
    plt.savefig("backtest_chart.png")
    plt.close()

    print("Gráfico guardado como 'backtest_chart.png'")

    # Step 4: Report
    print("\n" + "=" * 60)
    print("REPORTE DE BACKTESTING OPTIMIZADO")
    print("=" * 60)
    print(f"Capital Inicial:      ${initial_capital:,.2f}")
    print(f"Capital Final:        ${final_capital:,.2f}")
    print(f"Rendimiento Total:    {total_return_pct:,.2f} %")
    print(f"Total Operaciones:    {total_operations} (Compras: {buy_count}, Ventas: {sell_count})")
    print(f"Días Fear & Greed:    {sentiment_dates_covered} de {days} disponibles")
    print("=" * 60)


if __name__ == "__main__":
    run_backtest(initial_capital=10000, days=730)