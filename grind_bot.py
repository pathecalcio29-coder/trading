"""
Grid Trading Bot - Modalità SIMULATA (Paper Trading)
======================================================

Questo bot NON esegue ordini reali. Simula la strategia di grid trading
usando prezzi live (via ccxt) o storici, per testare la logica senza
rischiare soldi veri.

Requisiti:
    pip install ccxt --break-system-packages

Uso:
    python grid_bot.py
"""

import time
import json
import csv
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

try:
    import ccxt
except ImportError:
    ccxt = None
    print("⚠️  ccxt non installato. Installa con: pip install ccxt --break-system-packages")
    print("    Il bot può comunque girare con dati simulati (vedi SimulatedFeed).\n")

try:
    import requests
except ImportError:
    requests = None
    print("⚠️  requests non installato. Installa con: pip install requests --break-system-packages")


# ----------------------------------------------------------------------------
# CONNESSIONE SUPABASE
# ----------------------------------------------------------------------------
# Imposta queste variabili d'ambiente prima di avviare il bot (su Railway le
# aggiungi nella sezione "Variables" del progetto):
#   SUPABASE_URL=https://aymygtjocnhikzmtcmtj.supabase.co
#   SUPABASE_KEY=<anon key, vedi sotto>

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://aymygtjocnhikzmtcmtj.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF5bXlndGpvY25oaWt6bXRjbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEyODUxNjEsImV4cCI6MjA5Njg2MTE2MX0.pBTdtcWBKxv0lx8lytGUrGF9YXwQCawKXdyvqeXndjU")

# Lo schema si chiama "gridbot" (non "public"), quindi l'header Accept-Profile
# / Content-Profile serve per dire a PostgREST di usare quello schema.
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Accept-Profile": "gridbot",
    "Content-Profile": "gridbot",
    "Prefer": "return=minimal",
}


class SupabaseClient:
    """Client minimale per scrivere trade e stato wallet su Supabase (schema gridbot)."""

    def __init__(self, url: str, headers: dict):
        self.base = f"{url}/rest/v1"
        self.headers = headers

    def insert_trade(self, side: str, price: float, qty: float, usdt_amount: float,
                      fee: float, level: float, is_paper: bool = True):
        if requests is None:
            return
        payload = {
            "side": side, "price": price, "qty": qty,
            "usdt_amount": usdt_amount, "fee": fee,
            "level": level, "is_paper": is_paper,
        }
        try:
            r = requests.post(f"{self.base}/trades", headers=self.headers, json=payload, timeout=10)
            if r.status_code >= 300:
                print(f"⚠️  Errore scrittura trade su Supabase: {r.status_code} {r.text}")
        except Exception as e:
            print(f"⚠️  Errore di rete verso Supabase: {e}")

    def update_wallet(self, usdt_balance: float, asset_balance: float, last_price: float):
        if requests is None:
            return
        payload = {
            "id": 1, "usdt_balance": usdt_balance,
            "asset_balance": asset_balance, "last_price": last_price,
            "updated_at": datetime.now().isoformat(),
        }
        try:
            r = requests.post(
                f"{self.base}/wallet_state", headers={**self.headers, "Prefer": "resolution=merge-duplicates"},
                json=payload, timeout=10,
            )
            if r.status_code >= 300:
                print(f"⚠️  Errore aggiornamento wallet su Supabase: {r.status_code} {r.text}")
        except Exception as e:
            print(f"⚠️  Errore di rete verso Supabase: {e}")


# ----------------------------------------------------------------------------
# CONFIGURAZIONE
# ----------------------------------------------------------------------------

@dataclass
class GridConfig:
    symbol: str = "BTC/USDT"
    exchange_id: str = "binance"          # exchange da cui leggere i prezzi (solo lettura, no API key necessaria)
    lower_bound: float = 90_000.0         # limite inferiore della griglia
    upper_bound: float = 110_000.0        # limite superiore della griglia
    num_levels: int = 8                   # numero di livelli buy/sell
    capital_per_trade: float = 100.0      # capitale (in USDT) per ogni operazione
    fee_pct: float = 0.001                # fee exchange, es. 0.1% = 0.001
    starting_balance: float = 1000.0      # capitale simulato di partenza (USDT)
    poll_interval_sec: int = 15           # ogni quanto controllare il prezzo

    def build_levels(self) -> list[float]:
        """Genera i livelli di prezzo equidistanti nella griglia."""
        step = (self.upper_bound - self.lower_bound) / self.num_levels
        return [round(self.lower_bound + i * step, 2) for i in range(self.num_levels + 1)]


# ----------------------------------------------------------------------------
# STATO DEL PORTAFOGLIO SIMULATO
# ----------------------------------------------------------------------------

@dataclass
class PaperWallet:
    usdt_balance: float
    asset_balance: float = 0.0
    trade_log: list = field(default_factory=list)
    supabase: Optional[SupabaseClient] = None

    def buy(self, price: float, usdt_amount: float, fee_pct: float, level: Optional[float] = None):
        fee = usdt_amount * fee_pct
        net_usdt = usdt_amount - fee
        qty = net_usdt / price
        self.usdt_balance -= usdt_amount
        self.asset_balance += qty
        self._log("BUY", price, qty, usdt_amount, fee, level)
        return qty

    def sell(self, price: float, qty: float, fee_pct: float, level: Optional[float] = None):
        gross_usdt = qty * price
        fee = gross_usdt * fee_pct
        net_usdt = gross_usdt - fee
        self.usdt_balance += net_usdt
        self.asset_balance -= qty
        self._log("SELL", price, qty, net_usdt, fee, level)
        return net_usdt

    def _log(self, side: str, price: float, qty: float, usdt_amount: float, fee: float, level: Optional[float]):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "side": side,
            "price": price,
            "qty": round(qty, 8),
            "usdt_amount": round(usdt_amount, 2),
            "fee": round(fee, 4),
        }
        self.trade_log.append(entry)
        print(f"[{entry['timestamp']}] {side:4} | prezzo={price:.2f} | qty={entry['qty']:.6f} "
              f"| usdt={entry['usdt_amount']:.2f} | fee={entry['fee']:.4f}")

        if self.supabase:
            self.supabase.insert_trade(
                side=side, price=price, qty=round(qty, 8),
                usdt_amount=round(usdt_amount, 2), fee=round(fee, 4),
                level=level, is_paper=True,
            )
            self.supabase.update_wallet(
                usdt_balance=round(self.usdt_balance, 2),
                asset_balance=round(self.asset_balance, 8),
                last_price=price,
            )

    def total_value(self, current_price: float) -> float:
        return self.usdt_balance + self.asset_balance * current_price

    def export_csv(self, path: str = "trade_log.csv"):
        if not self.trade_log:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.trade_log[0].keys())
            writer.writeheader()
            writer.writerows(self.trade_log)
        print(f"\n📄 Log esportato in {path}")


# ----------------------------------------------------------------------------
# FONTE PREZZI: LIVE (ccxt) o SIMULATA (random walk)
# ----------------------------------------------------------------------------

class LivePriceFeed:
    """Legge prezzi reali in tempo reale da un exchange (solo lettura pubblica)."""

    def __init__(self, exchange_id: str, symbol: str):
        if ccxt is None:
            raise RuntimeError("ccxt non installato")
        self.exchange = getattr(ccxt, exchange_id)()
        self.symbol = symbol

    def get_price(self) -> float:
        ticker = self.exchange.fetch_ticker(self.symbol)
        return ticker["last"]


class SimulatedFeed:
    """Genera un prezzo simulato (random walk) per test offline senza connessione."""

    def __init__(self, start_price: float, volatility: float = 0.003):
        import random
        self._random = random
        self.price = start_price
        self.volatility = volatility

    def get_price(self) -> float:
        change_pct = self._random.uniform(-self.volatility, self.volatility)
        self.price = round(self.price * (1 + change_pct), 2)
        return self.price


# ----------------------------------------------------------------------------
# LOGICA DEL GRID BOT
# ----------------------------------------------------------------------------

class GridBot:
    def __init__(self, config: GridConfig, price_feed, wallet: PaperWallet):
        self.config = config
        self.feed = price_feed
        self.wallet = wallet
        self.levels = config.build_levels()
        # Ogni livello "buy" tiene traccia se è già stato acquistato (per non ricomprare)
        self.holdings_per_level: dict[float, Optional[float]] = {lvl: None for lvl in self.levels}
        self.last_price: Optional[float] = None

    def step(self):
        price = self.feed.get_price()

        # Trova il livello più vicino sotto e sopra il prezzo attuale
        for level in self.levels:
            qty_held = self.holdings_per_level[level]

            # Se il prezzo scende ad un livello vuoto -> compra
            if self.last_price is not None and price <= level < self.last_price and qty_held is None:
                if self.wallet.usdt_balance >= self.config.capital_per_trade:
                    qty = self.wallet.buy(price, self.config.capital_per_trade, self.config.fee_pct, level=level)
                    self.holdings_per_level[level] = qty
                else:
                    print("⚠️  Capitale insufficiente per comprare a questo livello")

            # Se il prezzo sale sopra un livello già acquistato -> vendi
            elif self.last_price is not None and price >= level > self.last_price and qty_held is not None:
                self.wallet.sell(price, qty_held, self.config.fee_pct, level=level)
                self.holdings_per_level[level] = None

        self.last_price = price
        return price

    def run(self, max_iterations: Optional[int] = None):
        print(f"\n🤖 Grid Bot avviato su {self.config.symbol}")
        print(f"   Range: {self.config.lower_bound} - {self.config.upper_bound}")
        print(f"   Livelli: {self.levels}")
        print(f"   Capitale iniziale: {self.wallet.usdt_balance} USDT\n")

        i = 0
        try:
            while max_iterations is None or i < max_iterations:
                price = self.step()
                value = self.wallet.total_value(price)
                print(f"   prezzo attuale: {price:.2f} | valore totale portafoglio: {value:.2f} USDT")
                time.sleep(self.config.poll_interval_sec)
                i += 1
        except KeyboardInterrupt:
            print("\n⏹️  Bot fermato manualmente")
        finally:
            final_price = self.last_price or 0
            print(f"\n📊 RISULTATO FINALE")
            print(f"   USDT liberi: {self.wallet.usdt_balance:.2f}")
            print(f"   Asset posseduto: {self.wallet.asset_balance:.6f}")
            print(f"   Valore totale: {self.wallet.total_value(final_price):.2f} USDT")
            print(f"   Profitto/Perdita: {self.wallet.total_value(final_price) - self.config.starting_balance:.2f} USDT")
            if not self.wallet.supabase:
                self.wallet.export_csv()  # fallback locale solo se Supabase non è collegato


# ----------------------------------------------------------------------------
# ESEMPIO DI ESECUZIONE
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    config = GridConfig(
        symbol="BTC/USDT",
        exchange_id="binance",
        lower_bound=90_000,
        upper_bound=110_000,
        num_levels=8,
        capital_per_trade=100,
        fee_pct=0.001,
        starting_balance=1000,
        poll_interval_sec=5,   # ridotto per demo veloce; nella realtà 15-60s
    )

    supabase_client = SupabaseClient(SUPABASE_URL, SUPABASE_HEADERS) if requests else None
    if supabase_client:
        print(f"✅ Collegato a Supabase: {SUPABASE_URL} (schema gridbot)\n")
    else:
        print("⚠️  Supabase disattivato (manca il pacchetto 'requests'): il bot gira solo in locale\n")

    wallet = PaperWallet(usdt_balance=config.starting_balance, supabase=supabase_client)

    # --- Scegli UNA delle due fonti di prezzo ---

    # 1) Simulata (nessuna connessione internet necessaria, buona per test rapidi)
    feed = SimulatedFeed(start_price=100_000, volatility=0.004)

    # 2) Live (dati reali dall'exchange, richiede ccxt + connessione internet)
    # feed = LivePriceFeed(exchange_id=config.exchange_id, symbol=config.symbol)

    bot = GridBot(config=config, price_feed=feed, wallet=wallet)
    bot.run(max_iterations=None)   # gira all'infinito, pensato per stare 24/7 su Railway
