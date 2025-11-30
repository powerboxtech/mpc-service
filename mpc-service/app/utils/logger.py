import sys
from loguru import logger
from app.core.config import settings


def setup_logging():
    """Configure loguru logging for the MPC service"""
    
    # Remove default handler
    logger.remove()
    
    # Add console handler with custom format
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
        colorize=True,
        backtrace=True,
        diagnose=True
    )
    
    # Add file handler for persistent logs
    logger.add(
        "logs/mpc_service.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="1 day",
        retention="30 days",
        compression="zip"
    )
    
    logger.info("Logging configuration initialized")


# Initialize logging when module is imported
setup_logging()