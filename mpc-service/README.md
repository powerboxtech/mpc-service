# MPC Battery Optimization Service

**Intelligent battery dispatch control for PowerBox Energy Management Platform**

---

## Overview

### About PowerBox Technology

PowerBox Technology develops integrated energy management solutions for commercial and industrial facilities. The **PowerBlock** platform intelligently orchestrates multiple energy sources (grid electricity, renewable generation, and battery storage) to minimize electricity costs while maximizing renewable energy utilization.

### What is Model Predictive Control?

**Model Predictive Control (MPC)** is an advanced optimization technique that "looks ahead" using forecasts to make better decisions. Unlike rule-based battery controllers that react to current conditions, MPC anticipates future electricity prices and load patterns to optimize battery dispatch over a 48-hour horizon.

**Key Advantages:**
- Anticipates future needs (won't drain battery before high-price periods)
- Globally optimal solutions considering constraints
- Adapts continuously with updated forecasts
- Achieves 15-30% cost reduction vs. rule-based control

---

## System Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                    Reporter Service (Port 8000)                 │
│  • Load Forecaster (hourly → resampled to 15-min)              │
│  • Solar Forecaster (15-min native resolution)                 │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ GET /api/forecasts/load
                 │ GET /api/forecasts/solar
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│               MPC Service - This Project (Port 8001)            │
│                                                                 │
│  • ForecastFetcher: Retrieves load/solar predictions           │
│  • MPCOptimizer: CVXPY optimization engine                     │
│  • BatteryClient: Communicates with BMS/Simulator              │
│  • Scheduler: Re-optimizes every 15 minutes                    │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ GET /api/battery/soc
                 │ POST /api/battery/dispatch
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│          Battery Simulator / BMS (Port 8002) [Future]           │
│  Testing: Battery simulator with SOC dynamics                  │
│  Production: Real Battery Management System                    │
└─────────────────────────────────────────────────────────────────┘
```

**Current Status:**
- ✅ Reporter integration working (fetches load/solar forecasts)
- ⚠️ BMS uses fallback SOC (0.5) - simulator to be built next
- ✅ CVXPY optimization fully functional

---

## How MPC Works

**Every 15 minutes:**

1. **Fetch Inputs**
   - Current battery SOC from BMS
   - 48-hour load forecast from Reporter (resampled from hourly to 15-min)
   - 48-hour solar forecast from Reporter (15-min resolution)
   - Time-of-Use electricity prices (Peak/Valley/Night rates)

2. **Optimize**
   - CVXPY solves 48-hour (192 time steps) optimization problem
   - Objective: Minimize energy cost + demand charges
   - Constraints: Battery limits, power balance, SOC ranges
   - Solve time: ~0.2 seconds

3. **Execute**
   - Extract first step from optimal schedule
   - Send battery power command to BMS
   - Store full schedule for API access

4. **Repeat**
   - Wait 15 minutes, shift horizon forward, re-optimize

---

## Project Structure
```
mpc-service/
├── app/
│   ├── main.py                  # FastAPI app + APScheduler
│   ├── core/
│   │   ├── config.py           # Settings (env vars + TOU rates)
│   │   └── models.py           # Pydantic data models
│   ├── mpc/
│   │   ├── optimizer.py        # CVXPY optimization logic
│   │   ├── forecasts.py        # Reporter client (load/solar)
│   │   └── battery_client.py   # BMS communication
│   └── api/
│       └── endpoints.py        # REST API routes
├── tests/                       # Unit tests
├── requirements.txt             # Python dependencies
├── .env.example                 # Configuration template
└── README.md
```

---

## Installation & Setup

### Prerequisites
- Python 3.12
- Anaconda (recommended)
- Access to Reporter service

### Quick Start

1. **Clone repository**
```bash
   git clone https://github.com/powerboxtech/mpc-service.git
   cd mpc-service
```

2. **Create Conda environment**
```bash
   conda create -n mpc-service python=3.12
   conda activate mpc-service
```

3. **Install dependencies**
```bash
   pip install -r requirements.txt
```

4. **Configure environment**
```bash
   cp .env.example .env
   # Edit .env with your Reporter URL and battery parameters
```

5. **Run service**
   
   **Using PyCharm/IDE:**
   - Script: `uvicorn`
   - Parameters: `app.main:app --reload`
   - Python interpreter: Select conda environment (Python 3.12)
   - Working directory: `mpc-service/`
   - Environment variables: Path to `.env` file

   **Using command line:**
```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

6. **Verify**
```bash
   # Check health
   curl http://localhost:8001/health
   
   # View API docs
   open http://localhost:8001/docs
```

---

## Configuration

### Key Environment Variables

**External Services:**
```env
REPORTER_BASE_URL=http://localhost:8000
BMS_BASE_URL=http://localhost:8002
```

**MPC Parameters:**
```env
MPC_INTERVAL_MINUTES=15      # Re-optimization frequency
MPC_HORIZON_HOURS=48         # Prediction horizon
```

**Battery Specifications:**
```env
BATTERY_CAPACITY_KWH=500.0
BATTERY_POWER_MAX_KW=250.0
BATTERY_EFFICIENCY_ROUNDTRIP=0.90
BATTERY_SOC_MIN=0.10
BATTERY_SOC_MAX=0.90
```

**Costa Rica Electricity Rates (CRC):**
```env
# Peak (10 AM - 5 PM)
PEAK_ENERGY_COST=70.0        # CRC/kWh
PEAK_DEMAND_COST=10154.0     # CRC/kW

# Valley (1 AM - 10 AM)
VALLEY_ENERGY_COST=26.0
VALLEY_DEMAND_COST=7090.0

# Nighttime (5 PM - 1 AM)
NIGHTTIME_ENERGY_COST=16.0
NIGHTTIME_DEMAND_COST=4541.0
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service health check |
| GET | `/api/mpc/current_dispatch` | Current battery power command |
| GET | `/api/mpc/full_schedule` | Complete 48-hour optimal schedule |
| GET | `/api/mpc/status` | MPC statistics (SOC, optimization count) |
| POST | `/api/mpc/trigger` | Manually trigger optimization |

**Interactive documentation:** http://localhost:8001/docs

---

## Implementation Details

### Optimization Formulation

**Decision Variables:**
- Battery power at each 15-min interval (192 steps)
- Grid power consumption
- Battery SOC trajectory

**Objective Function:**
```
minimize: Σ(TOU_price × P_grid × Δt) + demand_rate × peak(P_grid)
```

**Key Constraints:**
- Power balance: `P_grid + P_battery + P_solar = P_load`
- SOC dynamics with charge/discharge efficiency
- Battery power limits: ±250 kW
- SOC limits: 10% - 90%
- No grid export: `P_grid ≥ 0`

**Solver:** CVXPY with ECOS (convex optimization)

### Components

**MPCOptimizer (`optimizer.py`):**
- Formulates and solves CVXPY optimization problem
- Handles asymmetric charge/discharge efficiencies
- Returns optimal 48-hour schedule

**ForecastFetcher (`forecasts.py`):**
- Fetches hourly load forecast from Reporter
- Resamples to 15-min using pandas linear interpolation
- Fetches 15-min solar forecast (native resolution)
- Provides fallback forecasts if Reporter unavailable

**BatteryClient (`battery_client.py`):**
- Fetches current SOC from BMS/Simulator
- Sends battery dispatch commands
- Currently returns fallback SOC (0.5) until BMS available

**Scheduler (`main.py`):**
- APScheduler runs optimization every 15 minutes
- Updates global state with latest results
- Exposes results via REST API

---

## Testing
```bash
# Run all tests
pytest

# With coverage
pytest --cov=app tests/

# Specific test
pytest tests/test_optimizer.py -v
```

---

## Future Work

- **Battery Simulator/Validator Service:** Test MPC performance with simulated battery dynamics
- **Historical Validation:** Replay May-June 2025 data to quantify cost savings
- **BMS Integration:** Connect to real Battery Management System
- **Advanced Forecasting:** Weather-based solar, ML-enhanced load prediction
- **Uncertainty Quantification:** Stochastic MPC with forecast error modeling

---

## Dependencies

- **FastAPI** - Web framework
- **CVXPY** - Convex optimization
- **APScheduler** - Periodic task scheduling
- **Pandas** - Forecast resampling
- **Pydantic** - Data validation
- **Requests** - HTTP client

See `requirements.txt` for complete list.

---

## Contact

**PowerBox Technology**  
University of Illinois Research Park

For technical questions or collaboration:
- GitHub: [github.com/powerboxtech/mpc-service](https://github.com/powerboxtech/mpc-service)
- Email: [contact information]

---

*Built as part of ENG 573 Master's Capstone Project, Fall 2025*