import cvxpy as cp
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from loguru import logger
from app.core.config import settings


class MPCOptimizer:
    """MPC optimization engine using CVXPY for battery dispatch optimization"""
    
    def __init__(self):
        self.num_steps = settings.num_steps
        self.dt = settings.dt
        self.battery_capacity = settings.BATTERY_CAPACITY_KWH
        self.battery_power_max = settings.BATTERY_POWER_MAX_KW
        self.eta_charge = settings.eta_charge
        self.eta_discharge = settings.eta_discharge
        self.soc_min = settings.BATTERY_SOC_MIN
        self.soc_max = settings.BATTERY_SOC_MAX
        
        logger.info(f"Initialized MPCOptimizer with {self.num_steps} steps, "
                   f"dt={self.dt:.3f}h, capacity={self.battery_capacity}kWh")
    
    def optimize(
        self,
        soc_current: float,
        load_forecast: np.ndarray,
        solar_forecast: np.ndarray,
        timestamps: List[datetime],
        tou_prices: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        Solve MPC optimization problem using CVXPY
        
        Args:
            soc_current: Current battery SOC (0-1)
            load_forecast: Load forecast in kW for horizon
            solar_forecast: Solar forecast in kW for horizon  
            timestamps: Timestamps for each forecast point
            tou_prices: TOU energy prices (CRC/kWh), computed if None
            
        Returns:
            Dict containing optimization results with keys:
            - status: solver status ('optimal', 'infeasible', etc.)
            - P_battery: optimal battery power schedule [kW]
            - P_grid: optimal grid power schedule [kW]  
            - SOC: optimal SOC schedule [0-1]
            - P_charge: charging power schedule [kW]
            - P_discharge: discharging power schedule [kW]
            - peak_demand: peak grid demand [kW]
            - total_cost: total cost [CRC]
            - energy_cost: energy cost component [CRC]
            - demand_cost: demand cost component [CRC]
            - solve_time: solver time [seconds]
        """
        try:
            start_time = datetime.now()
            logger.info(f"Starting optimization with SOC={soc_current:.3f}")
            
            # Validate inputs
            if len(load_forecast) != self.num_steps:
                raise ValueError(f"Load forecast length {len(load_forecast)} != {self.num_steps}")
            if len(solar_forecast) != self.num_steps:
                raise ValueError(f"Solar forecast length {len(solar_forecast)} != {self.num_steps}")
            if len(timestamps) != self.num_steps:
                raise ValueError(f"Timestamps length {len(timestamps)} != {self.num_steps}")
                
            # Compute TOU prices if not provided
            if tou_prices is None:
                tou_prices = settings.get_tou_price_array(timestamps)
            
            # Determine demand charge rate (use first timestamp for simplicity)
            demand_rate = settings.get_demand_charge_rate(timestamps[0].hour)
            
            # Decision variables
            P_battery = cp.Variable(self.num_steps, name="P_battery")  # Battery power [kW]
            P_grid = cp.Variable(self.num_steps, name="P_grid")        # Grid power [kW]
            SOC = cp.Variable(self.num_steps + 1, name="SOC")          # State of charge [0-1]
            P_charge = cp.Variable(self.num_steps, name="P_charge")    # Charging power [kW]
            P_discharge = cp.Variable(self.num_steps, name="P_discharge") # Discharging power [kW]
            peak_demand = cp.Variable(name="peak_demand")              # Peak demand [kW]
            
            # Objective function
            energy_cost = cp.sum(cp.multiply(tou_prices, P_grid) * self.dt)
            demand_cost = demand_rate * peak_demand * self.dt  # Convert monthly rate to per-period
            total_cost = energy_cost + demand_cost
            
            objective = cp.Minimize(total_cost)
            
            # Constraints
            constraints = []
            
            # Initial SOC constraint
            constraints.append(SOC[0] == soc_current)
            
            # Power balance constraint: P_grid + P_battery + solar = load
            constraints.append(P_grid + P_battery + solar_forecast == load_forecast)
            
            # Battery power decomposition: P_battery = P_charge - P_discharge
            constraints.append(P_battery == P_charge - P_discharge)
            
            # SOC dynamics with efficiency
            for t in range(self.num_steps):
                soc_next = (SOC[t] + 
                           (self.eta_charge * P_charge[t] * self.dt / self.battery_capacity) -
                           (P_discharge[t] * self.dt / (self.eta_discharge * self.battery_capacity)))
                constraints.append(SOC[t + 1] == soc_next)
            
            # SOC bounds
            constraints.append(SOC >= self.soc_min)
            constraints.append(SOC <= self.soc_max)
            
            # Battery power limits
            constraints.append(P_battery >= -self.battery_power_max)  # Discharge limit
            constraints.append(P_battery <= self.battery_power_max)   # Charge limit
            
            # Charging/discharging power bounds
            constraints.append(P_charge >= 0)
            constraints.append(P_charge <= self.battery_power_max)
            constraints.append(P_discharge >= 0)
            constraints.append(P_discharge <= self.battery_power_max)
            
            # Grid power constraints
            constraints.append(P_grid >= 0)  # No grid export
            constraints.append(P_grid <= peak_demand)  # Peak demand constraint
            
            # Peak demand constraint (ensure it's at least the maximum grid power)
            constraints.append(peak_demand >= 0)
            
            # Create and solve problem
            problem = cp.Problem(objective, constraints)
            
            logger.debug("Starting CVXPY solver (ECOS)...")
            problem.solve(solver=cp.ECOS, verbose=False)
            
            solve_time = (datetime.now() - start_time).total_seconds()
            
            # Extract results
            if problem.status == cp.OPTIMAL:
                result = {
                    'status': 'optimal',
                    'P_battery': P_battery.value.tolist(),
                    'P_grid': P_grid.value.tolist(),
                    'SOC': SOC.value.tolist(),
                    'P_charge': P_charge.value.tolist(),
                    'P_discharge': P_discharge.value.tolist(),
                    'peak_demand': float(peak_demand.value),
                    'total_cost': float(problem.value),
                    'energy_cost': float(energy_cost.value),
                    'demand_cost': float(demand_cost.value),
                    'solve_time': solve_time
                }
                
                logger.info(f"Optimization successful: cost={result['total_cost']:.2f} CRC "
                           f"(energy={result['energy_cost']:.2f}, demand={result['demand_cost']:.2f}), "
                           f"solve_time={solve_time:.3f}s")
                logger.info(f"First step: P_battery={result['P_battery'][0]:.2f} kW, "
                           f"P_grid={result['P_grid'][0]:.2f} kW")
                
            else:
                logger.error(f"Optimization failed with status: {problem.status}")
                result = self._get_fallback_solution(soc_current, load_forecast, solar_forecast)
                result['solve_time'] = solve_time
                
        except Exception as e:
            logger.error(f"Optimization error: {e}")
            result = self._get_fallback_solution(soc_current, load_forecast, solar_forecast)
            result['solve_time'] = (datetime.now() - start_time).total_seconds()
            
        return result
    
    def _get_fallback_solution(
        self,
        soc_current: float,
        load_forecast: np.ndarray,
        solar_forecast: np.ndarray
    ) -> Dict[str, Any]:
        """
        Generate fallback solution when optimization fails
        Strategy: No battery action, grid supplies all net demand
        
        Args:
            soc_current: Current SOC
            load_forecast: Load forecast
            solar_forecast: Solar forecast
            
        Returns:
            Dict: Fallback solution with same structure as optimize()
        """
        logger.warning("Using fallback solution: no battery action")
        
        # Net demand = load - solar
        net_demand = load_forecast - solar_forecast
        P_grid = np.maximum(net_demand, 0)  # No grid export
        P_battery = np.zeros(self.num_steps)
        
        # SOC remains constant
        SOC = np.full(self.num_steps + 1, soc_current)
        
        # No charging/discharging
        P_charge = np.zeros(self.num_steps)
        P_discharge = np.zeros(self.num_steps)
        
        # Peak demand
        peak_demand = float(np.max(P_grid))
        
        # Estimate costs (approximate TOU pricing)
        avg_price = (settings.PEAK_ENERGY_COST + settings.VALLEY_ENERGY_COST + settings.NIGHTTIME_ENERGY_COST) / 3
        energy_cost = float(np.sum(P_grid) * self.dt * avg_price)
        demand_cost = float(peak_demand * settings.PEAK_DEMAND_COST * self.dt)
        total_cost = energy_cost + demand_cost
        
        return {
            'status': 'fallback',
            'P_battery': P_battery.tolist(),
            'P_grid': P_grid.tolist(), 
            'SOC': SOC.tolist(),
            'P_charge': P_charge.tolist(),
            'P_discharge': P_discharge.tolist(),
            'peak_demand': peak_demand,
            'total_cost': total_cost,
            'energy_cost': energy_cost,
            'demand_cost': demand_cost,
            'solve_time': 0.0
        }
    
    def validate_solution(self, result: Dict[str, Any]) -> bool:
        """
        Validate optimization solution for feasibility
        
        Args:
            result: Optimization result dictionary
            
        Returns:
            bool: True if solution is valid, False otherwise
        """
        try:
            if result['status'] not in ['optimal', 'fallback']:
                return False
                
            P_battery = np.array(result['P_battery'])
            SOC = np.array(result['SOC'])
            P_grid = np.array(result['P_grid'])
            
            # Check array lengths
            if len(P_battery) != self.num_steps:
                logger.error(f"Invalid P_battery length: {len(P_battery)}")
                return False
            if len(SOC) != self.num_steps + 1:
                logger.error(f"Invalid SOC length: {len(SOC)}")
                return False
            if len(P_grid) != self.num_steps:
                logger.error(f"Invalid P_grid length: {len(P_grid)}")
                return False
            
            # Check power limits
            if np.any(np.abs(P_battery) > self.battery_power_max + 1e-6):
                logger.error("Battery power limits violated")
                return False
            
            # Check SOC limits
            if np.any(SOC < self.soc_min - 1e-6) or np.any(SOC > self.soc_max + 1e-6):
                logger.error("SOC limits violated")
                return False
            
            # Check grid power non-negativity
            if np.any(P_grid < -1e-6):
                logger.error("Negative grid power detected")
                return False
            
            logger.debug("Solution validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Solution validation error: {e}")
            return False