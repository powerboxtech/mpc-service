from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List


class BatteryDispatch(BaseModel):
    """Primary output model - contains only the battery power command"""
    timestamp: datetime
    battery_power_kw: float  # Positive=charge, Negative=discharge
    status: str  # 'optimal', 'infeasible', etc.


class OptimalSchedule(BaseModel):
    """Complete optimal schedule over the prediction horizon"""
    timestamp: datetime
    horizon_hours: int
    battery_power_schedule: List[float]
    grid_power_schedule: List[float]
    soc_schedule: List[float]
    total_cost: float
    energy_cost: Optional[float] = None
    demand_cost: Optional[float] = None
    peak_demand: Optional[float] = None
    solver_status: str
    solver_time: Optional[float] = None


class MPCState(BaseModel):
    """Internal state tracking for the MPC service"""
    current_soc: float
    last_optimization_time: Optional[datetime] = None
    optimization_count: int
    last_battery_command: Optional[float] = None


class ForecastData(BaseModel):
    """Model for forecast data from Reporter service"""
    timestamps: List[datetime]
    values: List[float]
    forecast_type: str  # 'load' or 'solar'
    units: str  # 'kW'
    resolution_minutes: int


class BatteryStatus(BaseModel):
    """Model for battery status from BMS/Validator"""
    soc: float
    timestamp: datetime
    source: str  # 'bms' or 'simulator'


class DispatchCommand(BaseModel):
    """Model for sending dispatch commands to battery"""
    power_kw: float
    timestamp: datetime


class ServiceStatus(BaseModel):
    """Service status and health information"""
    service_name: str = "MPC Battery Optimization Service"
    version: str = "1.0.0"
    status: str
    uptime_seconds: float
    optimization_count: int
    last_optimization: Optional[datetime]
    current_soc: float
    last_battery_command: Optional[float]
    reporter_connected: bool
    bms_connected: bool