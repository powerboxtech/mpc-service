import requests
from datetime import datetime
from typing import Optional
from loguru import logger
from app.core.config import settings
from app.core.models import BatteryStatus, DispatchCommand


class BatteryClient:
    """Client for communicating with BMS/Validator service"""
    
    def __init__(self):
        self.base_url = settings.BMS_BASE_URL
        self.timeout = 10  # seconds
    
    def get_current_soc(self) -> float:
        """
        Fetch current SOC from BMS/Validator service
        
        Returns:
            float: Current state of charge (0-1)
        """
        try:
            url = f"{self.base_url}/api/battery/soc"
            logger.debug(f"Fetching SOC from: {url}")
            
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            soc = float(data["soc"])
            
            # Validate SOC range
            if not (0 <= soc <= 1):
                logger.warning(f"SOC value {soc} outside valid range [0,1], using fallback")
                return self.get_fallback_soc()
            
            logger.info(f"Retrieved SOC: {soc:.3f} from {data.get('source', 'unknown')}")
            return soc
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch SOC from BMS: {e}")
            return self.get_fallback_soc()
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Invalid SOC response format: {e}")
            return self.get_fallback_soc()
    
    def send_dispatch_command(self, power_kw: float) -> bool:
        """
        Send battery power command to BMS/Validator service
        
        Args:
            power_kw (float): Battery power command in kW
                            Positive = charge, Negative = discharge
        
        Returns:
            bool: True if command sent successfully, False otherwise
        """
        try:
            url = f"{self.base_url}/api/battery/dispatch"
            
            command = DispatchCommand(
                power_kw=power_kw,
                timestamp=datetime.now()
            )
            
            logger.debug(f"Sending dispatch command to: {url}")
            logger.info(f"Battery command: {power_kw:.2f} kW")
            
            response = requests.post(
                url,
                json=command.dict(),
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            logger.info(f"Successfully sent battery command: {power_kw:.2f} kW")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Failed to send dispatch command to BMS: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending dispatch command: {e}")
            return False
    
    def get_fallback_soc(self) -> float:
        """
        Return fallback SOC value when BMS is unavailable
        
        Returns:
            float: Fallback SOC value
        """
        fallback_soc = settings.BATTERY_INITIAL_SOC
        logger.warning(f"Using fallback SOC: {fallback_soc}")
        return fallback_soc
    
    def test_connection(self) -> bool:
        """
        Test connection to BMS/Validator service
        
        Returns:
            bool: True if service is reachable, False otherwise
        """
        try:
            url = f"{self.base_url}/health"
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            logger.info("BMS/Validator service connection successful")
            return True
        except requests.RequestException as e:
            logger.warning(f"BMS/Validator service not reachable: {e}")
            return False