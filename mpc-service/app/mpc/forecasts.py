import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Tuple, List
from loguru import logger
from app.core.config import settings


class ForecastFetcher:
    """Client for fetching forecasts from Reporter service"""
    
    def __init__(self):
        self.reporter_url = settings.REPORTER_BASE_URL
        self.timeout = 15  # seconds
        self.horizon_hours = settings.MPC_HORIZON_HOURS
        self.time_step_minutes = settings.MPC_TIME_STEP_MINUTES
        self.headers = {
            'Authorization': f'Bearer {settings.REPORTER_AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
    
    def fetch_load_forecast(self) -> Tuple[np.ndarray, List[datetime]]:
        """
        Fetch hourly load forecast and resample to 15-min intervals
        
        The Reporter API returns 168 hours of data starting from start of current day.
        We crop to our horizon and resample to our time resolution.
        
        Returns:
            Tuple[np.ndarray, List[datetime]]: Load values in kW and timestamps
        """
        try:
            url = f"{self.reporter_url}/api/forecasts/load/poi_1"
            
            logger.debug(f"Fetching load forecast from: {url}")
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            df['ds'] = pd.to_datetime(df['ds'])
            df = df.rename(columns={'ds': 'timestamp', 'hourly_power': 'value'})
            df.set_index('timestamp', inplace=True)
            
            # Resample from hourly to time_step_minutes using linear interpolation FIRST
            target_freq = f"{self.time_step_minutes}T"  # T = minutes
            df_resampled = df.resample(target_freq).interpolate(method='linear')
            
            # THEN crop to our horizon starting from now
            now = datetime.now()
            end_time = now + timedelta(hours=self.horizon_hours)
            df_cropped = df_resampled[now:end_time]
            
            # Extract values and timestamps for our exact horizon
            target_length = settings.num_steps
            load_values = df_cropped['value'].values[:target_length]
            timestamps = df_cropped.index.to_pydatetime().tolist()[:target_length]
            
            # Validate we have the expected length
            if len(load_values) != target_length:
                logger.warning(
                    f"Load forecast length {len(load_values)} != expected {target_length}, "
                    f"using fallback"
                )
                return self._get_fallback_load_forecast()
            
            logger.info(f"Retrieved load forecast: {len(load_values)} points, "
                       f"range: {load_values.min():.1f}-{load_values.max():.1f} kW")
            
            return load_values, timestamps
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch load forecast: {e}")
            return self._get_fallback_load_forecast()
        except Exception as e:
            logger.error(f"Error processing load forecast: {e}")
            return self._get_fallback_load_forecast()
    
    def fetch_solar_forecast(self) -> Tuple[np.ndarray, List[datetime]]:
        """
        Fetch 15-min solar forecast from Reporter service
        
        The Reporter API returns 168 hours of 15-minute data starting from start of current day.
        We crop to our horizon.
        
        Returns:
            Tuple[np.ndarray, List[datetime]]: Solar values in kW and timestamps
        """
        try:
            url = f"{self.reporter_url}/api/forecasts/solar/poi_1"
            
            logger.debug(f"Fetching solar forecast from: {url}")
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            # Convert to DataFrame
            df = pd.DataFrame(data)
            df['index'] = pd.to_datetime(df['index'])
            df = df.rename(columns={'index': 'timestamp', 'power_expected': 'value'})
            df.set_index('timestamp', inplace=True)
            
            # Crop to our horizon starting from now
            now = datetime.now()
            end_time = now + timedelta(hours=self.horizon_hours)
            df_cropped = df[now:end_time]
            
            # Extract values and timestamps for our exact horizon
            target_length = settings.num_steps
            solar_values = df_cropped['value'].values[:target_length]
            timestamps = df_cropped.index.to_pydatetime().tolist()[:target_length]
            
            # Validate we have the expected length
            if len(solar_values) != target_length:
                logger.warning(
                    f"Solar forecast length {len(solar_values)} != expected {target_length}, "
                    f"using fallback"
                )
                return self._get_fallback_solar_forecast()
            
            logger.info(f"Retrieved solar forecast: {len(solar_values)} points, "
                       f"range: {solar_values.min():.1f}-{solar_values.max():.1f} kW")
            
            return solar_values, timestamps
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch solar forecast: {e}")
            return self._get_fallback_solar_forecast()
        except Exception as e:
            logger.error(f"Error processing solar forecast: {e}")
            return self._get_fallback_solar_forecast()
    
    def _get_fallback_load_forecast(self) -> Tuple[np.ndarray, List[datetime]]:
        """
        Generate fallback load forecast (constant 200 kW)
        
        Returns:
            Tuple[np.ndarray, List[datetime]]: Fallback load values and timestamps
        """
        logger.warning("Using fallback load forecast: constant 200 kW")
        
        # Generate timestamps
        now = datetime.now()
        timestamps = [
            now + timedelta(minutes=i * self.time_step_minutes)
            for i in range(settings.num_steps)
        ]
        
        # Constant load
        load_values = np.full(settings.num_steps, 200.0)
        
        return load_values, timestamps
    
    def _get_fallback_solar_forecast(self) -> Tuple[np.ndarray, List[datetime]]:
        """
        Generate fallback solar forecast (zero generation)
        
        Returns:
            Tuple[np.ndarray, List[datetime]]: Fallback solar values and timestamps
        """
        logger.warning("Using fallback solar forecast: zero generation")
        
        # Generate timestamps
        now = datetime.now()
        timestamps = [
            now + timedelta(minutes=i * self.time_step_minutes)
            for i in range(settings.num_steps)
        ]
        
        # Zero solar generation
        solar_values = np.zeros(settings.num_steps)
        
        return solar_values, timestamps
    
    def test_connection(self) -> bool:
        """
        Test connection to Reporter service
        
        Returns:
            bool: True if service is reachable, False otherwise
        """
        try:
            url = f"{self.reporter_url}/health"
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            logger.info("Reporter service connection successful")
            return True
        except requests.RequestException as e:
            logger.warning(f"Reporter service not reachable: {e}")
            return False