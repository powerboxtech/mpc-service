from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from loguru import logger
import asyncio
import atexit

# Import configuration and components
from app.core.config import settings
from app.core.models import MPCState, BatteryDispatch, OptimalSchedule
from app.mpc.optimizer import MPCOptimizer
from app.mpc.forecasts import ForecastFetcher
from app.mpc.battery_client import BatteryClient
from app.api.endpoints import router as mpc_router
from app.utils.logger import setup_logging

# Initialize FastAPI app
app = FastAPI(
    title="MPC Battery Optimization Service",
    description="Model Predictive Control service for optimizing battery energy storage dispatch",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state variables
mpc_state = MPCState(
    current_soc=settings.BATTERY_INITIAL_SOC,
    optimization_count=0
)
current_dispatch = None
current_schedule = None

# Initialize MPC components
optimizer = MPCOptimizer()
forecast_fetcher = ForecastFetcher()
battery_client = BatteryClient()

# Scheduler for periodic optimization
scheduler = BackgroundScheduler()


async def run_mpc_optimization() -> bool:
    """
    Main MPC optimization loop - runs every 15 minutes
    
    Returns:
        bool: True if optimization successful, False otherwise
    """
    global mpc_state, current_dispatch, current_schedule
    
    try:
        logger.info("=== Starting MPC Optimization Cycle ===")
        
        # Step 1: Fetch current SOC from BMS/Validator
        logger.debug("Fetching current SOC from BMS...")
        soc_current = battery_client.get_current_soc()
        logger.info(f"Current SOC: {soc_current:.3f}")
        
        # Step 2: Fetch forecasts from Reporter service
        logger.debug("Fetching forecasts from Reporter...")
        load_forecast, timestamps = forecast_fetcher.fetch_load_forecast()
        solar_forecast, _ = forecast_fetcher.fetch_solar_forecast()
        
        logger.info(f"Load forecast: {len(load_forecast)} points, "
                   f"range {load_forecast.min():.1f}-{load_forecast.max():.1f} kW")
        logger.info(f"Solar forecast: {len(solar_forecast)} points, "
                   f"range {solar_forecast.min():.1f}-{solar_forecast.max():.1f} kW")
        
        # Step 3: Run optimization
        logger.debug("Running CVXPY optimization...")
        optimization_result = optimizer.optimize(
            soc_current=soc_current,
            load_forecast=load_forecast,
            solar_forecast=solar_forecast,
            timestamps=timestamps
        )
        
        # Step 4: Process optimization results
        if optimization_result['status'] in ['optimal', 'fallback']:
            # Extract first step battery command
            battery_power_kw = float(optimization_result['P_battery'][0])
            
            logger.info(f"Optimization successful: {optimization_result['status']}")
            logger.info(f"Battery command: {battery_power_kw:.2f} kW "
                       f"({'charge' if battery_power_kw > 0 else 'discharge' if battery_power_kw < 0 else 'idle'})")
            
            # Send command to battery system
            logger.debug("Sending battery dispatch command...")
            command_sent = battery_client.send_dispatch_command(battery_power_kw)
            
            if command_sent:
                logger.info("Battery command sent successfully")
            else:
                logger.warning("Failed to send battery command")
            
            # Update global state
            current_dispatch = BatteryDispatch(
                timestamp=datetime.now(),
                battery_power_kw=battery_power_kw,
                status=optimization_result['status']
            )
            
            current_schedule = OptimalSchedule(
                timestamp=datetime.now(),
                horizon_hours=settings.MPC_HORIZON_HOURS,
                battery_power_schedule=optimization_result['P_battery'],
                grid_power_schedule=optimization_result['P_grid'],
                soc_schedule=optimization_result['SOC'],
                total_cost=optimization_result['total_cost'],
                energy_cost=optimization_result.get('energy_cost'),
                demand_cost=optimization_result.get('demand_cost'),
                peak_demand=optimization_result.get('peak_demand'),
                solver_status=optimization_result['status'],
                solver_time=optimization_result.get('solve_time')
            )
            
            # Update MPC state
            mpc_state.current_soc = float(optimization_result['SOC'][1])  # Next SOC
            mpc_state.last_optimization_time = datetime.now()
            mpc_state.optimization_count += 1
            mpc_state.last_battery_command = battery_power_kw
            
            logger.info(f"=== MPC Cycle Complete (#{mpc_state.optimization_count}) ===")
            return True
            
        else:
            logger.error(f"Optimization failed with status: {optimization_result['status']}")
            
            # Create failure dispatch
            current_dispatch = BatteryDispatch(
                timestamp=datetime.now(),
                battery_power_kw=0.0,
                status=optimization_result['status']
            )
            
            mpc_state.last_optimization_time = datetime.now()
            mpc_state.optimization_count += 1
            
            return False
            
    except Exception as e:
        logger.error(f"MPC optimization error: {str(e)}", exc_info=True)
        
        # Create error dispatch
        current_dispatch = BatteryDispatch(
            timestamp=datetime.now(),
            battery_power_kw=0.0,
            status="error"
        )
        
        mpc_state.last_optimization_time = datetime.now()
        
        return False


def run_mpc_optimization_sync():
    """Synchronous wrapper for the async MPC optimization function"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_mpc_optimization())
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Error in sync optimization wrapper: {e}")
        return False


@app.on_event("startup")
async def startup_event():
    """Initialize service on startup"""
    logger.info("🚀 Starting MPC Battery Optimization Service")
    logger.info(f"Configuration: {settings.MPC_HORIZON_HOURS}h horizon, "
               f"{settings.MPC_TIME_STEP_MINUTES}min timesteps")
    logger.info(f"Battery: {settings.BATTERY_CAPACITY_KWH}kWh, "
               f"{settings.BATTERY_POWER_MAX_KW}kW")
    
    # Start the scheduler
    scheduler.add_job(
        func=run_mpc_optimization_sync,
        trigger=IntervalTrigger(minutes=settings.MPC_INTERVAL_MINUTES),
        id='mpc_optimization',
        name='MPC Optimization Loop',
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30
    )
    
    scheduler.start()
    logger.info(f"Scheduler started: optimization every {settings.MPC_INTERVAL_MINUTES} minutes")
    
    # Run initial optimization
    logger.info("Running initial optimization...")
    await run_mpc_optimization()
    
    # Register cleanup function
    atexit.register(lambda: scheduler.shutdown())
    
    logger.info("🟢 MPC Service startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown"""
    logger.info("🛑 Shutting down MPC Service")
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


# Include API routers
app.include_router(mpc_router, prefix="/api/mpc", tags=["MPC"])


# Root endpoints
@app.get("/")
async def root():
    """Service information endpoint"""
    return {
        "service": "MPC Battery Optimization Service",
        "version": "1.0.0",
        "description": "Model Predictive Control for battery energy storage dispatch optimization",
        "endpoints": {
            "current_dispatch": "/api/mpc/current_dispatch",
            "full_schedule": "/api/mpc/full_schedule", 
            "status": "/api/mpc/status",
            "trigger": "/api/mpc/trigger",
            "docs": "/docs",
            "health": "/health"
        },
        "timestamp": datetime.now()
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Basic health indicators
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now(),
            "service": "MPC Battery Optimization Service",
            "version": "1.0.0",
            "mpc_state": {
                "current_soc": mpc_state.current_soc,
                "optimization_count": mpc_state.optimization_count,
                "last_optimization": mpc_state.last_optimization_time
            },
            "scheduler_running": scheduler.running if scheduler else False
        }
        
        # Test external connections (commented out per requirements)
        # reporter_ok = forecast_fetcher.test_connection()
        # bms_ok = battery_client.test_connection()
        # health_status["external_services"] = {
        #     "reporter": reporter_ok,
        #     "bms": bms_ok
        # }
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(),
            "error": str(e)
        }


if __name__ == "__main__":
    import uvicorn
    
    # Setup logging
    setup_logging()
    
    uvicorn.run(
        "app.main:app",
        host=settings.SERVICE_HOST,
        port=settings.SERVICE_PORT,
        reload=False,
        log_level=settings.LOG_LEVEL.lower()
    )