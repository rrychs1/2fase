import logging
from logging.handlers import RotatingFileHandler
import os
from dotenv import load_dotenv

load_dotenv()

def setup_logger():
    # Use level from env or default to INFO
    log_level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Cleaner format for cloud/docker
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    
    # Clear existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()

    # Console Handler (Must for Docker/DigitalOcean)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File Handler (Optional, based on env)
    log_to_file = os.getenv('LOG_TO_FILE', 'true').lower() == 'true'
    if log_to_file:
        if not os.path.exists('logs'):
            os.makedirs('logs')
        file_handler = RotatingFileHandler('logs/bot.log', maxBytes=10*1024*1024, backupCount=10)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger
