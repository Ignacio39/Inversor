import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "bot_trading"))

import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
import yfinance as yf
import requests
import pandas as pd
from datetime import datetime
from typing import Optional, List, Dict

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
                nuevo_capital = capital_restante * 0.9
                posicion_abierta = True
                print(f"🚨 ALERTA: [COMPRA EJECUTADA] @ ${price:,.2f}")
            else:
                print("Mercado estable. Sin señal de compra.")
        else:
            # Condición de VENTA: SMA_20 < SMA_50 (ruptura de tendencia)
            if sma_20 < sma_50:
                tipo_operacion = "VENTA"
                nuevo_capital = capital_restante * 1.1
                posicion_abierta = False
                print(f"🚨 ALERTA: [VENTA EJECUTADA] @ ${price:,.2f}")
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
    """Leer estado actual de la cuenta desde Firestore."""
    try:
        state = get_bot_state()
        return {
            "capital": state.get("capital_restante", 10000.0),
            "posicion_abierta": state.get("posicion_abierta", False)
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