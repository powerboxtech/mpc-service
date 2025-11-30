from pydantic_settings import BaseSettings
from typing import List
import numpy as np
from math import sqrt
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()


class Settings(BaseSettings):
    # Service configuration
    SERVICE_HOST: str
    SERVICE_PORT: int
    LOG_LEVEL: str
    
    # External service URLs
    REPORTER_BASE_URL: str
    BMS_BASE_URL: str
    
    # Authentication
    REPORTER_AUTH_TOKEN: str
    
    # MPC configuration
    MPC_INTERVAL_MINUTES: int
    MPC_TIME_STEP_MINUTES: int
    MPC_HORIZON_HOURS: int
    
    # Battery parameters
    BATTERY_CAPACITY_KWH: float
    BATTERY_POWER_MAX_KW: float
    BATTERY_EFFICIENCY_ROUNDTRIP: float
    BATTERY_SOC_MIN: float
    BATTERY_SOC_MAX: float
    BATTERY_INITIAL_SOC: float
    
    # TOU energy rates (CRC/kWh)
    PEAK_ENERGY_COST: float
    VALLEY_ENERGY_COST: float
    NIGHTTIME_ENERGY_COST: float
    
    # Demand charges (CRC/kW)
    PEAK_DEMAND_COST: float
    VALLEY_DEMAND_COST: float
    NIGHTTIME_DEMAND_COST: float
    
    # TOU period definitions (hours)
    PEAK_START_HOUR: int
    PEAK_END_HOUR: int
    VALLEY_START_HOUR: int
    VALLEY_END_HOUR: int
    NIGHTTIME_START_HOUR: int
    NIGHTTIME_END_HOUR: int
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @property
    def num_steps(self) -> int:
        """Number of optimization steps in horizon"""
        return int(self.MPC_HORIZON_HOURS * 60 / self.MPC_TIME_STEP_MINUTES)
    
    @property
    def dt(self) -> float:
        """Time step in hours"""
        return self.MPC_TIME_STEP_MINUTES / 60.0
    
    @property
    def eta_charge(self) -> float:
        """Charging efficiency (η) - square root of roundtrip efficiency"""
        return sqrt(self.BATTERY_EFFICIENCY_ROUNDTRIP)
    
    @property
    def eta_discharge(self) -> float:
        """Discharging efficiency (η) - square root of roundtrip efficiency"""
        return sqrt(self.BATTERY_EFFICIENCY_ROUNDTRIP)
    
    def get_tou_price_array(self, timestamps: List) -> np.ndarray:
        """Get TOU energy prices for given timestamps"""
        prices = []
        for ts in timestamps:
            hour = ts.hour
            if self.PEAK_START_HOUR <= hour < self.PEAK_END_HOUR:
                prices.append(self.PEAK_ENERGY_COST)
            elif self.VALLEY_START_HOUR <= hour < self.VALLEY_END_HOUR:
                prices.append(self.VALLEY_ENERGY_COST)
            else:  # Nighttime
                prices.append(self.NIGHTTIME_ENERGY_COST)
        return np.array(prices)
    
    def get_demand_charge_rate(self, hour: int) -> float:
        """Get demand charge rate for given hour"""
        if self.PEAK_START_HOUR <= hour < self.PEAK_END_HOUR:
            return self.PEAK_DEMAND_COST
        elif self.VALLEY_START_HOUR <= hour < self.VALLEY_END_HOUR:
            return self.VALLEY_DEMAND_COST
        else:  # Nighttime
            return self.NIGHTTIME_DEMAND_COST


# Global settings instance
settings = Settings()