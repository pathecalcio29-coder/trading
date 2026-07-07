import React, { useState, useEffect, useRef } from "react";
import { LineChart, Line, XAxis, YAxis, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import { Play, Pause, TrendingUp, TrendingDown, Circle } from "lucide-react";

// ---------------------------------------------------------------------------
// Dashboard collegata a Supabase (schema gridbot). Il bot Python (grid_bot.py)
// gira separatamente su Railway 24/7 e scrive qui: trades, wallet_state.
// Questa pagina è SOLO lettura — non esegue mai ordini.
// ---------------------------------------------------------------------------

const SUPABASE_URL = "https://aymygtjocnhikzmtcmtj.supabase.co";
const SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF5bXlndGpvY25oaWt6bXRjbXRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODEyODUxNjEsImV4cCI6MjA5Njg2MTE2MX0.pBTdtcWBKxv0lx8lytGUrGF9YXwQCawKXdyvqeXndjU";

const REST_HEADERS = {
  apikey: SUPABASE_KEY,
  Authorization: `Bearer ${SUPABASE_KEY}`,
  "Accept-Profile": "gridbot",
  "Content-Type": "application/json",
};

const CONFIG = {
  symbol: "BTC/USDT",
  lowerBound: 90000,
  upperBound: 110000,
  numLevels: 8,
  capitalPerTrade: 100,
  feePct: 0.001,
  startingBalance: 1000,
};

function buildLevels(cfg) {
  const step = (cfg.upperBound - cfg.lowerBound) / cfg.numLevels;
  return Array.from({ length: cfg.numLevels + 1 }, (_, i) => cfg.lowerBound + i * step);
}

async function fetchWalletState() {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/wallet_state?id=eq.1&select=*`, { headers: REST_HEADERS });
  if (!res.ok) throw new Error(`wallet_state: ${res.status}`);
  const rows = await res.json();
  return rows[0] || null;
}

async function fetchRecentTrades(limit = 30) {
  const res = await fetch(
    `${SUPABASE_URL}/rest/v1/trades?select=*&order=created_at.desc&limit=${limit}`,
    { headers: REST_HEADERS }
  );
  if (!res.ok) throw new Error(`trades: ${res.status}`);
  return res.json();
}

export default function GridBotDashboard() {
  const [price, setPrice] = useState(null);
  const [history, setHistory] = useState([]);
  const [wallet, setWallet] = useState({ usdt: CONFIG.startingBalance, asset: 0 });
  const [trades, setTrades] = useState([]);
  const [heldLevels, setHeldLevels] = useState({});
  const [connError, setConnError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const tickRef = useRef(0);

  const levels = buildLevels(CONFIG);

  async function refresh() {
    try {
      const [walletRow, tradeRows] = await Promise.all([fetchWalletState(), fetchRecentTrades()]);

      if (walletRow) {
        setWallet({ usdt: Number(walletRow.usdt_balance), asset: Number(walletRow.asset_balance) });
        if (walletRow.last_price != null) {
          const p = Number(walletRow.last_price);
          setPrice(p);
          tickRef.current += 1;
          setHistory((h) => [...h, { t: tickRef.current, price: p }].slice(-60));
        }
      }

      setTrades(
        tradeRows.map((t) => ({
          side: t.side,
          price: Number(t.price),
          qty: Number(t.qty),
          amount: Number(t.usdt_amount),
        }))
      );

      // Ricostruisce quali livelli hanno una posizione aperta guardando
      // se l'ultima operazione su quel livello è stata BUY senza SELL successiva
      const byLevel = {};
      [...tradeRows].reverse().forEach((t) => {
        if (t.level == null) return;
        if (t.side === "BUY") byLevel[t.level] = true;
        else byLevel[t.level] = false;
      });
      setHeldLevels(byLevel);

      setConnError(null);
      setLastUpdate(new Date());
    } catch (e) {
      setConnError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000); // polling ogni 5s
    return () => clearInterval(interval);
  }, []);

  const totalValue = price != null ? wallet.usdt + wallet.asset * price : wallet.usdt;
  const pnl = totalValue - CONFIG.startingBalance;
  const pnlPct = (pnl / CONFIG.startingBalance) * 100;

  return (
    <div style={{ minHeight: "100vh", background: "#0B0E14", color: "#E4E7EB", fontFamily: "'JetBrains Mono', 'Courier New', monospace", padding: "24px" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;600;700&display=swap');
        * { box-sizing: border-box; }
        .label { font-family: 'JetBrains Mono', monospace; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: #6B7280; }
        .panel { background: #11151C; border: 1px solid #1E242E; border-radius: 6px; }
        .mono-num { font-variant-numeric: tabular-nums; }
        button:focus-visible, .clickable:focus-visible { outline: 2px solid #4ADE80; outline-offset: 2px; }
      `}</style>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: "22px", fontWeight: 700, letterSpacing: "-0.01em" }}>
            grid<span style={{ color: "#4ADE80" }}>_</span>bot
          </div>
          <div className="label">{CONFIG.symbol} · paper trading · dati live da Supabase</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px" }}>
          <Circle size={8} fill={connError ? "#F87171" : "#4ADE80"} stroke="none" />
          <span className="label" style={{ color: connError ? "#F87171" : "#6B7280" }}>
            {connError ? "Connessione persa" : lastUpdate ? `Aggiornato ${lastUpdate.toLocaleTimeString()}` : "Connessione…"}
          </span>
        </div>
      </div>

      {connError && (
        <div className="panel" style={{ padding: "12px 16px", marginBottom: "16px", border: "1px solid #7F1D1D", background: "#1A1112" }}>
          <span style={{ fontSize: "12px", color: "#F87171" }}>
            Impossibile leggere da Supabase ({connError}). Controlla che il bot sia in esecuzione su Railway e che le tabelle esistano.
          </span>
        </div>
      )}

      {/* Stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "12px", marginBottom: "16px" }}>
        <StatCard label="Prezzo attuale" value={price != null ? `$${price.toLocaleString()}` : "—"} />
        <StatCard label="Valore totale" value={`$${totalValue.toFixed(2)}`} />
        <StatCard
          label="Profitto / Perdita"
          value={`${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)} (${pnlPct.toFixed(2)}%)`}
          color={pnl >= 0 ? "#4ADE80" : "#F87171"}
          icon={pnl >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
        />
        <StatCard label="USDT liberi" value={`$${wallet.usdt.toFixed(2)}`} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "16px", marginBottom: "16px" }}>
        {/* Chart */}
        <div className="panel" style={{ padding: "16px" }}>
          <div className="label" style={{ marginBottom: "12px" }}>Prezzo &amp; livelli griglia</div>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={history}>
              <XAxis dataKey="t" hide />
              <YAxis domain={[CONFIG.lowerBound - 2000, CONFIG.upperBound + 2000]} stroke="#374151" tick={{ fontSize: 10, fill: "#6B7280" }} width={55} />
              <Tooltip
                contentStyle={{ background: "#11151C", border: "1px solid #1E242E", borderRadius: "6px", fontSize: "12px" }}
                labelFormatter={() => ""}
                formatter={(v) => [`$${v}`, "prezzo"]}
              />
              {levels.map((l) => (
                <ReferenceLine key={l} y={l} stroke="#1E242E" strokeDasharray="3 3" />
              ))}
              <Line type="monotone" dataKey="price" stroke="#4ADE80" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Grid levels */}
        <div className="panel" style={{ padding: "16px" }}>
          <div className="label" style={{ marginBottom: "12px" }}>Livelli</div>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {[...levels].reverse().map((level) => {
              const held = heldLevels[level];
              const isCurrent = price != null && Math.abs(level - price) < (CONFIG.upperBound - CONFIG.lowerBound) / CONFIG.numLevels / 2;
              return (
                <div
                  key={level}
                  style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "6px 10px", borderRadius: "4px", fontSize: "12px",
                    background: isCurrent ? "#1A2E22" : "transparent",
                    border: isCurrent ? "1px solid #2D5940" : "1px solid transparent",
                  }}
                  className="mono-num"
                >
                  <span style={{ color: isCurrent ? "#4ADE80" : "#9CA3AF" }}>${level.toLocaleString()}</span>
                  <Circle size={7} fill={held ? "#4ADE80" : "#374151"} stroke="none" />
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Trade log */}
      <div className="panel" style={{ padding: "16px" }}>
        <div className="label" style={{ marginBottom: "12px" }}>Storico operazioni</div>
        {trades.length === 0 ? (
          <div style={{ color: "#6B7280", fontSize: "13px", padding: "12px 0" }}>
            Nessuna operazione ancora. Avvia il bot per vedere i trade comparire qui.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "2px", maxHeight: "260px", overflowY: "auto" }}>
            {trades.map((t, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "60px 1fr 1fr 1fr", gap: "8px", padding: "8px 10px", fontSize: "12px", borderBottom: "1px solid #1E242E" }} className="mono-num">
                <span style={{ color: t.side === "BUY" ? "#4ADE80" : "#F87171", fontWeight: 700 }}>{t.side}</span>
                <span>${t.price.toLocaleString()}</span>
                <span style={{ color: "#9CA3AF" }}>{t.qty.toFixed(6)}</span>
                <span style={{ color: "#9CA3AF" }}>${t.amount.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color = "#E4E7EB", icon }) {
  return (
    <div className="panel" style={{ padding: "14px 16px" }}>
      <div className="label" style={{ marginBottom: "6px" }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "18px", fontWeight: 700, color }} className="mono-num">
        {icon}
        {value}
      </div>
    </div>
  );
}