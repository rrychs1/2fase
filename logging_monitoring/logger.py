import logging
from logging.handlers import RotatingFileHandler
import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

class JsonFormatter(logging.Formatter):
    """
    Format logs as structured JSON telemetry natively mapped for ELK/Datadog ingests.
    Captures native extras `{"event", "timestamp", "symbol", "pnl"}` gracefully.
    """
    def format(self, record):
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        
        # Merge structurally required observability keys dynamically
        if hasattr(record, "event") or hasattr(record, "symbol") or hasattr(record, "pnl"):
            log_obj["event"] = getattr(record, "event", "LogEvent")
            log_obj["symbol"] = getattr(record, "symbol", "SYSTEM")
            log_obj["pnl"] = getattr(record, "pnl", 0.0)
            
        # Catch arbitrary injected extras natively passed into `logging.info(msg, extra={})`
        excluded_keys = {'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename', 'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated', 'thread', 'threadName', 'processName', 'process', 'message', 'event', 'symbol', 'pnl'}
        for key, value in record.__dict__.items():
            if key not in excluded_keys:
                log_obj[key] = value

        return json.dumps(log_obj)

def setup_logger():
    log_level_name = os.getenv('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Use Strict JSON Formatter universally
    formatter = JsonFormatter()
    
    if logger.hasHandlers():
        logger.handlers.clear()

    # Console Handler (Cloud/Docker ingestion)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    log_to_file = os.getenv('LOG_TO_FILE', 'true').lower() == 'true'
    if log_to_file:
        if not os.path.exists('logs'):
            os.makedirs('logs')
        # Structure log output files directly to `.json.log` for machine parsers
        file_handler = RotatingFileHandler('logs/bot.json.log', maxBytes=10*1024*1024, backupCount=10)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger
