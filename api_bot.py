import sys
import os
import webbrowser
from threading import Timer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "bot_trading"))

import os
from datetime import datetime
from decimal import Decimal
from dotenv import load_dotenv
from binance.client import Client
from firebase_admin import credentials, firestore
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
import yfinance as yf
import requests
import pandas as pd
from typing import Optional, List, Dict

# Load environment variables from .env file
load_dotenv()

# Inicializar cliente de Binance con credenciales reales
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

if BINANCE_API_KEY and BINANCE_SECRET_KEY:
    binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
else:
    binance_client = None
    print("⚠️  Advertencia: Credenciales de Binance no configuradas. Ejecutándose en modo simulación.")

# Initialize FastAPI
app = FastAPI()

# Firebase initialization
try:
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"Error initializing Firebase: {e}")
    db = None

# CryptoBot integration
from bot_core import CryptoBot
from live_bot import LiveTradingBot

bot = LiveTradingBot()

# --- Database Functions ---


def get_bot_state() -> dict:
    """Read bot state from Firestore colección bot_state, documento current."""
    if db is None:
        return {"posicion_abierta": False, "capital_restante": 10000.0}
    try:
        doc = db.collection("bot_state").document("current").get()
        if doc.exists:
            return doc.to_dict()
        else:
            db.collection("bot_state").document("current").set({
                "posicion_abierta": False,
                "capital_restante": 10000.0
            })
            return {"posicion_abierta": False, "capital_restante": 10000.0}
    except Exception as e:
        print(f"Error reading bot state: {e}")
        return {"posicion_abierta": False, "capital_restante": 10000.0}


def update_bot_state(posicion_abierta: bool, capital_restante: float):
    """Write bot state to Firestore."""
    if db is None:
        return
    try:
        db.collection("bot_state").document("current").set({
            "posicion_abierta": posicion_abierta,
            "capital_restante": capital_restante
        })
    except Exception as e:
        print(f"Error updating bot state: {e}")


def add_trade_history(price: float, tipo: str, capital_restante: float):
    """Register each order in colección trade_history."""
    if db is None:
        return
    try:
        db.collection("trade_history").add({
            "fecha": datetime.now(),
            "precio": price,
            "tipo": tipo,
            "capital_restante": capital_restante
        })
    except Exception as e:
        print(f"Error adding trade history: {e}")


def get_trade_history() -> List[dict]:
    """Extract complete operation history from Firestore."""
    if db is None:
        return []
    try:
        docs = db.collection("trade_history").stream()
        history = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            history.append(data)
        return history
    except Exception as e:
        print(f"Error getting trade history: {e}")
        return []


def get_binance_usdt_balance() -> float:
    """Obtener saldo real de USDT desde Binance."""
    if binance_client is None:
        return 10000.0
    try:
        balance = binance_client.get_asset_balance(asset='USDT')
        if balance:
            return float(balance['free'])
        return 10000.0
    except Exception as e:
        print(f"Error fetching USDT balance from Binance: {e}")
        return 10000.0


def get_binance_btc_balance() -> float:
    """Obtener saldo real de BTC desde Binance."""
    if binance_client is None:
        return 0.0
    try:
        balance = binance_client.get_asset_balance(asset='BTC')
        if balance:
            return float(balance['free'])
        return 0.0
    except Exception as e:
        print(f"Error fetching BTC balance from Binance: {e}")
        return 0.0


def place_market_buy(symbol: str, quote_order_qty: float) -> dict:
    """Ejecutar orden de COMPRA real en Binance."""
    if binance_client is None:
        print("⚠️  Cliente de Binance no disponible - orden simulada")
        return {"status": "simulated", "order_type": "BUY", "quantity": quote_order_qty}
    try:
        order = binance_client.order_market_buy(symbol=symbol, quoteOrderQty=quote_order_qty)
        return {"status": "executed", "order_id": order.get("orderId"), "symbol": symbol, "quantity": float(order.get("executedQty")), "price": float(order["fills"][0]["price"])}
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error executing BUY order: {error_msg}")
        # Intentar guardar error en Firestore
        if db is not None:
            try:
                db.collection("trade_history").add({
                    "fecha": datetime.now(),
                    "precio": 0,
                    "tipo": "ERROR_BUY",
                    "capital_restante": 0,
                    "error": error_msg[:200]
                })
            except:
                pass
        return {"status": "error", "message": error_msg}


def place_market_sell(symbol: str, quantity: float) -> dict:
    """Ejecutar orden de VENTA real en Binance."""
    if binance_client is None:
        print("⚠️  Cliente de Binance no disponible - orden simulada")
        return {"status": "simulated", "order_type": "SELL", "quantity": quantity}
    try:
        # First check if we have enough balance
        btc_balance = get_binance_btc_balance()
        if quantity > btc_balance:
            return {"status": "error", "message": f"Saldo insuficiente: tienes {btc_balance} BTC, intentando vender {quantity}"}
        order = binance_client.order_market_sell(symbol=symbol, quantity=quantity)
        return {"status": "executed", "order_id": order.get("orderId"), "symbol": symbol, "quantity": float(order.get("executedQty")), "price": float(order["fills"][0]["price"])}
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error executing SELL order: {error_msg}")
        # Intentar guardar error en Firestore
        if db is not None:
            try:
                db.collection("trade_history").add({
                    "fecha": datetime.now(),
                    "precio": 0,
                    "tipo": "ERROR_SELL",
                    "capital_restante": 0,
                    "error": error_msg[:200]
                })
            except:
                pass
        return {"status": "error", "message": error_msg}


# --- Background Task: trade_logic ---


def trade_logic():
    """Revisar mercado, evaluar SMA y Fear & Greed, ejecutar operación si hay señal."""
    try:
        # Leer estado actual desde Firestore
        state = get_bot_state()
        posicion_abierta = state.get("posicion_abierta", False)
        capital_restante = state.get("capital_restante", 10000.0)

        # Obtener datos de mercado
        market_data = bot.get_live_market_data()
        if market_data is None:
            print("❌ No se pudieron obtener datos de mercado. Reintentando...")
            return

        price = market_data["price"]
        sma_20 = market_data["sma_20"]
        sma_50 = market_data["sma_50"]

        # Obtener Fear & Greed
        sentiment = bot.fetch_live_sentiment()
        fg_value = sentiment["value"] if sentiment else 50

        # Evaluar señal de trading
        nuevo_capital = capital_restante
        tipo_operacion = None

        if not posicion_abierta:
            # Condición de COMPRA: SMA_20 > SMA_50 AND Fear & Greed <= 75
            if sma_20 > sma_50 and fg_value <= 75:
                tipo_operacion = "COMPRA"
                # Ejecutar orden real en Binance
                result = place_market_buy('BTCUSDT', 20)
                if result["status"] == "executed":
                    nuevo_capital = capital_restante - 20  # Restar el monto usado
                    posicion_abierta = True
                    print(f"🚨 ALERTA: [COMPRA EJECUTADA en Binance] @ ${price:,.2f}")
                    print(f"   Order ID: {result['order_id']}, Cantidad: {result['quantity']} BTC")
                else:
                    print(f"❌ Fallo en orden de COMPRA: {result.get('message', 'Unknown error')}")
            else:
                print("Mercado estable. Sin señal de compra.")
        else:
            # Condición de VENTA: SMA_20 < SMA_50 (ruptura de tendencia)
            if sma_20 < sma_50:
                tipo_operacion = "VENTA"
                # Obtener saldo actual de BTC y vender todo
                btc_balance = get_binance_btc_balance()
                result = place_market_sell('BTCUSDT', btc_balance)
                if result["status"] == "executed":
                    nuevo_capital = capital_restante + (btc_balance * price)
                    posicion_abierta = False
                    print(f"🚨 ALERTA: [VENTA EJECUTADA en Binance] @ ${price:,.2f}")
                    print(f"   Order ID: {result['order_id']}, Vendido: {result['quantity']} BTC")
                else:
                    print(f"❌ Fallo en orden de VENTA: {result.get('message', 'Unknown error')}")
            else:
                print("Posición activa. Monitoreando tendencia...")

        # Guardar nuevo estado e historial si hubo operación
        if tipo_operacion:
            update_bot_state(posicion_abierta, nuevo_capital)
            add_trade_history(price, tipo_operacion, nuevo_capital)

    except Exception as e:
        print(f"Error en trade_logic: {e}")


# --- Background Scheduler ---


def start_scheduler():
    """Programar revisión de mercado cada 4 horas (14400 segundos)."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(trade_logic, "interval", seconds=14400)
    scheduler.start()

# Iniciar scheduler al cargar la aplicación
start_scheduler()

# Abrir automáticamente la documentación de la API en el navegador
@app.on_event("startup")
def open_docs():
    """Abrir la docs de FastAPI en el navegador después de 1 segundo."""
    Timer(1, lambda: webbrowser.open("http://localhost:8000/docs")).start()


# --- REST Endpoints ---


@app.get("/")
async def root():
    return {"status": "Bot de Trading Activo y monitoreando"}


@app.get("/market-status")
async def market_status():
    """Devuelve precio actual, SMA_20, SMA_50 y Fear & Greed Index."""
    try:
        market_data = bot.get_live_market_data()
        if market_data is None:
            return {"error": "Could not fetch market data"}

        sentiment = bot.fetch_live_sentiment()
        fg_value = sentiment["value"] if sentiment else 50

        return {
            "precio_actual": market_data["price"],
            "sma_20": market_data["sma_20"],
            "sma_50": market_data["sma_50"],
            "fear_greed_index": fg_value
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/portfolio")
async def portfolio():
    """Leer estado actual de la cuenta usando saldos reales de Binance."""
    try:
        if binance_client is not None:
            # Obtener saldos reales de Binance
            usdt_balance = get_binance_usdt_balance()
            btc_balance = get_binance_btc_balance()
            
            # Calcular capital total en USDT
            capital_total = usdt_balance + (btc_balance * 8000)  # Precio estimado para referencia
            
            # Determinar si hay posición abierta
            posicion_abierta = btc_balance > 0.001  # Umbral mínimo
            
            return {
                "capital": round(capital_total, 2),
                "posicion_abierta": posicion_abierta,
                "usdt_balance": round(usdt_balance, 2),
                "btc_balance": round(btc_balance, 6),
                "fuente": "binance_real"
            }
        else:
            # Modo simulador - leer de Firestore
            state = get_bot_state()
            return {
                "capital": state.get("capital_restante", 10000.0),
                "posicion_abierta": state.get("posicion_abierta", False),
                "fuente": "firestore_simulacion"
            }
    except Exception as e:
        return {"error": str(e)}


@app.get("/history")
async def history():
    """Extraer historial completo de operaciones desde Firestore."""
    try:
        history = get_trade_history()
        return {"historial": history}
    except Exception as e:
        return {"error": str(e)}