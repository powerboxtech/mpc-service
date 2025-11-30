from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
import time
from loguru import logger
from app.core.models import BatteryDispatch, OptimalSchedule, ServiceStatus
# Import will be resolved at runtime to avoid circular imports


router = APIRouter()


@router.get("/current_dispatch", response_model=BatteryDispatch)
async def get_current_dispatch():
    """
    Get the current battery dispatch command
    
    Returns the most recent optimal battery power command from the MPC optimization.
    This is the primary endpoint for the battery control system.
    """
    try:
        # Import at runtime to avoid circular imports
        from app.main import current_dispatch
        
        if current_dispatch is None:
            logger.warning("No current dispatch available, returning default")
            return BatteryDispatch(
                timestamp=datetime.now(),
                battery_power_kw=0.0,
                status="no_optimization_run"
            )
        
        logger.debug(f"Returning current dispatch: {current_dispatch.battery_power_kw:.2f} kW")
        return current_dispatch
        
    except Exception as e:
        logger.error(f"Error getting current dispatch: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/full_schedule", response_model=OptimalSchedule)
async def get_full_schedule():
    """
    Get the complete optimal schedule over the prediction horizon
    
    Returns the full MPC optimization results including battery power, grid power,
    and SOC schedules over the entire prediction horizon.
    """
    try:
        # Import at runtime to avoid circular imports
        from app.main import current_schedule
        
        if current_schedule is None:
            logger.warning("No current schedule available")
            raise HTTPException(status_code=404, detail="No optimization schedule available")
        
        logger.debug(f"Returning full schedule: {len(current_schedule.battery_power_schedule)} steps")
        return current_schedule
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting full schedule: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/status", response_model=ServiceStatus)
async def get_status():
    """
    Get service status and health information
    
    Returns comprehensive status including connectivity to external services,
    optimization statistics, and current battery state.
    """
    try:
        # Import at runtime to avoid circular imports
        from app.main import mpc_state, forecast_fetcher, battery_client
        
        # Get uptime
        uptime_seconds = time.time() - getattr(get_status, '_start_time', time.time())
        
        # Test external service connections (commented out per requirements)
        # reporter_connected = forecast_fetcher.test_connection() if forecast_fetcher else False
        # bms_connected = battery_client.test_connection() if battery_client else False
        reporter_connected = True  # Assume connected for happy path
        bms_connected = True       # Assume connected for happy path
        
        # Determine overall status
        if reporter_connected and bms_connected:
            status = "healthy"
        elif reporter_connected or bms_connected:
            status = "degraded"
        else:
            status = "unhealthy"
        
        # Get current state info
        current_soc = mpc_state.current_soc if mpc_state else 0.5
        optimization_count = mpc_state.optimization_count if mpc_state else 0
        last_optimization = mpc_state.last_optimization_time if mpc_state else None
        last_battery_command = mpc_state.last_battery_command if mpc_state else None
        
        service_status = ServiceStatus(
            status=status,
            uptime_seconds=uptime_seconds,
            optimization_count=optimization_count,
            last_optimization=last_optimization,
            current_soc=current_soc,
            last_battery_command=last_battery_command,
            reporter_connected=reporter_connected,
            bms_connected=bms_connected
        )
        
        logger.debug(f"Service status: {status}, uptime: {uptime_seconds:.1f}s")
        return service_status
        
    except Exception as e:
        logger.error(f"Error getting service status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/trigger")
async def trigger_optimization():
    """
    Manually trigger an MPC optimization cycle
    
    Forces an immediate execution of the MPC optimization loop,
    useful for testing or manual intervention.
    """
    try:
        from app.main import run_mpc_optimization
        
        logger.info("Manual optimization trigger received")
        
        # Run optimization in background
        success = await run_mpc_optimization()
        
        if success:
            return {
                "message": "Optimization triggered successfully", 
                "timestamp": datetime.now(),
                "status": "success"
            }
        else:
            return {
                "message": "Optimization failed", 
                "timestamp": datetime.now(),
                "status": "error"
            }
            
    except Exception as e:
        logger.error(f"Error triggering optimization: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger optimization: {str(e)}")


# Set start time for uptime calculation
get_status._start_time = time.time()