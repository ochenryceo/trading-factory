# 🚀 Go-Live Checklist — Sunday March 29, 22:15 UTC

## 🔌 Infrastructure (before market open)
- [ ] All 4 PaperExecutors running on NinjaTrader
- [ ] Signal queue reachable: `curl http://YOUR_SERVER_IP:8088/signals/status`
- [ ] Webhook responding: `curl http://YOUR_SERVER_IP:8088/health`
- [ ] Discord logging live (test message to #paper-trading-live)

## 📊 State
- [ ] All positions = flat (no stale positions)
- [ ] Signal queue empty: `curl http://YOUR_SERVER_IP:8088/signals/status` → pending=0
- [ ] Logs clean: check `/tmp/webhook.log` for errors

## 🔒 Safety
- [ ] Kill switch test: toggle ON then OFF
- [ ] Max contracts = 1 per strategy, 4 total
- [ ] NinjaTrader account = Sim/Paper confirmed

## 🔬 First 15 Minutes — OBSERVE ONLY
Watch for:

### 1. Signal Flow
- Does a signal appear in logs?
- Does the correct chart pick it up?
- Does only ONE chart respond per signal?

### 2. Execution Integrity
- Order placed once (not twice)
- Correct direction
- Correct quantity (1 contract)

### 3. Feedback Loop
- Fill → logged at /ninja/status
- Discord → alert posted
- Metrics → updated at /signals/status

## 🚨 KILL IMMEDIATELY if:
- Duplicate trades
- Wrong strategy executing
- Orders firing without signals
- Positions not matching logs
- Executor freezing or lagging >60s

Kill command: `curl -X POST http://YOUR_SERVER_IP:8088/signals/kill -H "Content-Type: application/json" -d '{"secret":"YOUR_SECRET_HERE","disabled":true}'`

## ✅ Day 1 Success Criteria
- Clean executions (no mismatches)
- No crashes
- Logs match reality
- Discord alerts firing
- PnL doesn't matter — system integrity does
