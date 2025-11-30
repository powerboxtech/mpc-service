# MPC Battery Optimization Service

A FastAPI-based Model Predictive Control (MPC) service for optimizing battery energy storage dispatch in commercial and industrial facilities. This service is part of PowerBox Technology's energy management platform for Costa Rica's high-cost electricity market.

## 🏗️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Reporter       │    │   MPC Service   │    │ Validator/BMS   │
│  Service        │◄───┤   (Port 8001)   ├───►│   Service       │
│  (Port 8000)    │    │                 │    │  (Port 8002)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
       │                         │                        │
       ├─ Load Forecasts         ├─ Battery Optimization  ├─ Battery Control
       ├─ Solar Forecasts        ├─ Cost Minimization     ├─ SOC Monitoring  
       └─ 48h Horizon            └─ 15min Re-optimization └─ Power Commands
```

### Service Integration

1. **Reporter Service** (External - Port 8000):
   - Provides hourly load forecasts (resampled to 15-min by MPC)
   - Provides 15-minute solar generation forecasts
   - Endpoints: `/api/forecasts/load`, `/api/forecasts/solar`

2. **MPC Service** (This Service - Port 8001):
   - Fetches forecasts from Reporter service
   - Fetches current battery SOC from Validator/BMS
   - Runs CVXPY optimization every 15 minutes
   - Outputs optimal battery power commands
   - Pure optimization logic - no simulation or validation

3. **Validator Service** (External - Port 8002):
   - Battery simulator for testing (alternative to real BMS)
   - Tracks simulated SOC based on MPC commands
   - Power flow accounting and cost calculations
   - Endpoints: `/api/battery/soc`, `/api/battery/dispatch`

## ⚡ How MPC Works

The Model Predictive Control algorithm operates on a **receding horizon** principle:

### 15-Minute Optimization Cycle:
1. **Fetch Current State**: Get current battery SOC from BMS/Validator
2. **Fetch Forecasts**: Get 48-hour load and solar forecasts from Reporter  
3. **Solve Optimization**: Use CVXPY to minimize total electricity cost:
   - **Objective**: `minimize(energy_cost + demand_cost)`
   - **Energy Cost**: `∑(TOU_price[t] × P_grid[t] × dt)`
   - **Demand Cost**: `demand_rate × peak_demand`
4. **Send Command**: Dispatch only the **first step** of optimal solution
5. **Wait**: Sleep for 15 minutes, then repeat with updated forecasts

### Costa Rican Time-of-Use (TOU) Rates:
- **Peak Hours** (10 AM - 5 PM): 70 CRC/kWh + 10,154 CRC/kW demand
- **Valley Hours** (1 AM - 10 AM): 26 CRC/kWh + 7,090 CRC/kW demand  
- **Nighttime Hours** (5 PM - 1 AM): 16 CRC/kWh + 4,541 CRC/kW demand

## 🚀 Quick Start

### 1. Installation

```bash
# Clone repository
git clone <repository-url>
cd mpc-service

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env file with your settings
```

### 2. Configuration

Key configuration parameters in `.env`:

```bash
# Service Configuration
SERVICE_HOST=0.0.0.0
SERVICE_PORT=8001
LOG_LEVEL=INFO

# External Services
REPORTER_BASE_URL=http://localhost:8000
BMS_BASE_URL=http://localhost:8002

# MPC Parameters
MPC_INTERVAL_MINUTES=15
MPC_HORIZON_HOURS=48
MPC_TIME_STEP_MINUTES=15

# Battery Specifications
BATTERY_CAPACITY_KWH=500.0
BATTERY_POWER_MAX_KW=250.0
BATTERY_EFFICIENCY_ROUNDTRIP=0.90
BATTERY_SOC_MIN=0.10
BATTERY_SOC_MAX=0.90
```

### 3. Run the Service

```bash
# Development mode
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

# Production mode
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

### 4. Docker Deployment

```bash
# Build image
docker build -t mpc-service .

# Run container
docker run -p 8001:8001 --env-file .env mpc-service
```

## 📡 API Endpoints

### Core MPC Endpoints

#### `GET /api/mpc/current_dispatch`
Get the current battery power command (primary endpoint for battery controller).

**Response:**
```json
{
  "timestamp": "2025-01-15T14:30:00Z",
  "battery_power_kw": -75.5,
  "status": "optimal"
}
```
- `battery_power_kw`: Positive = charge, Negative = discharge
- `status`: "optimal", "fallback", "infeasible", "error"

#### `GET /api/mpc/full_schedule` 
Get complete optimal schedule over 48-hour horizon.

**Response:**
```json
{
  "timestamp": "2025-01-15T14:30:00Z",
  "horizon_hours": 48,
  "battery_power_schedule": [-75.5, -80.2, ...],
  "grid_power_schedule": [120.3, 115.8, ...],
  "soc_schedule": [0.65, 0.63, 0.61, ...],
  "total_cost": 12500.50,
  "energy_cost": 8200.30,
  "demand_cost": 4300.20,
  "peak_demand": 180.5,
  "solver_status": "optimal",
  "solver_time": 0.245
}
```

#### `GET /api/mpc/status`
Service health and statistics.

#### `POST /api/mpc/trigger`
Manually trigger optimization (for testing).

### Service Info

#### `GET /`
Service information and available endpoints.

#### `GET /health`
Health check endpoint.

#### `GET /docs`
Interactive API documentation (Swagger UI).

## 🧮 Optimization Details

### Decision Variables (CVXPY)
- `P_battery[N]`: Battery power schedule [kW]
- `P_grid[N]`: Grid power schedule [kW] 
- `SOC[N+1]`: State of charge schedule [0-1]
- `P_charge[N]`: Charging power [kW] ≥ 0
- `P_discharge[N]`: Discharging power [kW] ≥ 0
- `peak_demand`: Peak grid demand [kW]

### Key Constraints
```python
# Initial condition
SOC[0] == soc_current

# Power balance  
P_grid[t] + P_battery[t] + solar_forecast[t] == load_forecast[t]

# Battery power decomposition
P_battery[t] == P_charge[t] - P_discharge[t]

# SOC dynamics with efficiency
SOC[t+1] == SOC[t] + (η_charge × P_charge[t] × dt / capacity)
                   - (P_discharge[t] × dt / (η_discharge × capacity))

# Operational limits
SOC_min ≤ SOC[t] ≤ SOC_max
0 ≤ P_charge[t] ≤ P_max
0 ≤ P_discharge[t] ≤ P_max  
P_grid[t] ≥ 0  # No grid export
P_grid[t] ≤ peak_demand
```

### Solver Configuration
- **Solver**: CVXPY with ECOS backend
- **Fallback**: If optimization fails, return zero battery command
- **Validation**: Comprehensive solution feasibility checking

## 🗂️ Project Structure

```
mpc-service/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app + APScheduler
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # Pydantic Settings (.env loader)
│   │   └── models.py              # API data models
│   ├── mpc/
│   │   ├── __init__.py
│   │   ├── optimizer.py           # CVXPY optimization engine
│   │   ├── forecasts.py           # Reporter service client
│   │   └── battery_client.py      # BMS/Validator service client
│   ├── api/
│   │   ├── __init__.py
│   │   └── endpoints.py           # API route handlers
│   └── utils/
│       ├── __init__.py
│       └── logger.py              # Loguru configuration
├── tests/
│   ├── __init__.py
│   ├── test_optimizer.py
│   ├── test_forecasts.py
│   └── test_battery_client.py
├── .env                           # Configuration file
├── .env.example                   # Configuration template
├── .gitignore
├── requirements.txt
├── Dockerfile
└── README.md
```

## 🔧 Development

### Running Tests
```bash
pytest tests/ -v
```

### Code Quality
```bash
# Format code
black app/ tests/

# Lint
flake8 app/ tests/

# Type checking  
mypy app/
```

### Logging
The service uses structured logging with Loguru:
- Console output: Colorized, human-readable
- File output: `logs/mpc_service.log` with rotation
- Log levels: DEBUG, INFO, WARNING, ERROR

## 🐛 Troubleshooting

### Common Issues

#### 1. Optimization Failures
```
ERROR: Optimization failed with status: infeasible
```
**Solutions:**
- Check battery SOC limits and power constraints
- Verify forecast data quality (no NaN/infinite values)
- Review TOU pricing configuration
- Check logs for constraint violations

#### 2. Service Connection Errors
```
ERROR: Failed to fetch forecasts from Reporter: ConnectionError
```
**Solutions:**
- Verify Reporter service is running on configured URL
- Check network connectivity between services
- Review firewall rules
- Fallback forecasts will be used automatically

#### 3. Scheduler Issues
```
WARNING: APScheduler job missed fire time
```
**Solutions:**
- Ensure optimization completes within 15-minute window
- Check system resource availability
- Review optimization solver performance
- Consider reducing horizon or increasing time steps

### Configuration Validation
The service validates critical configuration on startup:
- Battery parameters (capacity, power limits, efficiency)
- TOU rate definitions
- Service URL connectivity
- MPC timing parameters

### Performance Monitoring
Key metrics to monitor:
- **Optimization solve time** (target: <30 seconds)
- **API response times** (target: <1 second)
- **Memory usage** (CVXPY can be memory-intensive)
- **Scheduler execution frequency** (every 15 minutes)

## 📋 Production Checklist

Before deploying to production:

- [ ] Configure real BMS/Validator service URLs
- [ ] Validate battery parameters match physical system
- [ ] Test optimization with realistic load/solar profiles  
- [ ] Set up monitoring and alerting
- [ ] Configure log retention policies
- [ ] Review security settings (firewall, authentication)
- [ ] Test failover scenarios (service outages)
- [ ] Validate cost calculations with actual utility bills

## 📄 License

[Add your license information here]

## 🤝 Contributing

[Add contribution guidelines here]

## 📞 Support

For issues and questions:
- Create an issue in the repository
- Contact: [Add contact information]