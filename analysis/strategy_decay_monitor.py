import pandas as pd
import numpy as np
from typing import Dict, List, Any
import logging
from analysis.performance_drift import PerformanceDriftDetector

logger = logging.getLogger(__name__)

class StrategyDecayMonitor:
    """
    Lightweight background orchestrator that manages and monitors the health 
    of multiple concurrent trading strategies using Performance Drift Detection.
    """

    def __init__(self, alert_manager=None):
        # Dictionary storing the active configuration and history for each registered strategy
        self.strategies: Dict[str, Dict[str, Any]] = {}
        self.alert_manager = alert_manager

    def register_strategy(self, strategy_id: str, config_overrides: dict = None) -> None:
        """
        Registers a new strategy to the monitor with optional custom alert thresholds.
        """
        base_config = {
            "min_trades": 100,
            "recent_window": 50,
            "historical_baseline_window": None, # None = Expanding historical window
            "health_warning_threshold": 40.0,
            "health_critical_threshold": 15.0,
            "deterioration_warning_drop": 20.0, # Rapid drop in score between 2 evaluations
            "weights": {
                'rolling_sharpe': 0.35,
                'rolling_win_rate': 0.15,
                'rolling_profit_factor': 0.25,
                'current_drawdown_pnl': 0.25 # Expanded weighting for Drawdown monitoring
            }
        }
        
        if config_overrides:
            base_config.update(config_overrides)
            if 'weights' in config_overrides:
                base_config['weights'] = config_overrides['weights']
                
        self.strategies[strategy_id] = {
            "config": base_config,
            "trades_df": pd.DataFrame(),
            "previous_health_score": 100.0,
            "current_health_score": 100.0,
            "last_classification": "NORMAL",
            "active_alerts": []
        }
        logger.info(f"Registered Strategy: {strategy_id} for Decay Monitoring.")

    def update_trades(self, strategy_id: str, trades_df: pd.DataFrame) -> None:
        """
        Feeds the latest trade ledger for a specific strategy into the monitor.
        """
        if strategy_id not in self.strategies:
            logger.warning(f"Unregistered strategy: {strategy_id}. Auto-registering with default config.")
            self.register_strategy(strategy_id)
            
        self.strategies[strategy_id]["trades_df"] = trades_df.copy()

    @staticmethod
    def zscore_to_health_score(z: float) -> float:
        """
        Uses a continuous Sigmoid (Logistic) transformation mapping to convert an 
        unbounded Z-score [-inf, +inf] into a readable Health Score [0, 100].
        Centered such that Z=0 yields score~=90, and Z=-2.5 yields score~=10.
        """
        # Linear shift and scale: We want Z=0 -> high health, Z<0 dropping smoothly.
        # We don't care if a strategy is outperforming the baseline (Z > 0), Health stays ~100.
        
        # Cap positive Z to avoid extremely large numbers in exponent
        z_capped = min(max(z, -10.0), 5.0)
        
        # Logistic parameters tuned for:
        # Z = 0    -> ~95
        # Z = -1.5 -> ~50
        # Z = -2.5 -> ~15
        # Z = -3.5 -> ~5
        
        k = 1.8 # steepness
        z0 = -1.5 # midpoint
        
        sigmoid = 1.0 / (1.0 + np.exp(-k * (z_capped - z0)))
        return float(sigmoid * 100.0)

    def evaluate_strategy_health(self, strategy_id: str) -> dict:
        """
        Computes the current strategy health score chaining into Performance Drift metrics.
        Returns evaluation dict and triggers state updates for rapid deterioration checks.
        """
        if strategy_id not in self.strategies:
            return {}
            
        strat = self.strategies[strategy_id]
        trades = strat["trades_df"]
        cfg = strat["config"]
        
        drift_res = PerformanceDriftDetector.calculate_drift(
            trades_df=trades,
            recent_window=cfg["recent_window"],
            historical_baseline_window=cfg["historical_baseline_window"],
            min_trades=cfg["min_trades"],
            use_percentiles=True,
            weights=cfg["weights"]
        )
        
        if drift_res.get("classification") == "INSUFFICIENT_DATA":
            alert_payload = {
                "strategy_id": strategy_id,
                "status": "INSUFFICIENT_DATA",
                "health_score": 100.0,
                "alerts": []
            }
            return alert_payload
            
        z_score = drift_res["drift_score_z"]
        health_score = self.zscore_to_health_score(z_score)
        
        # State tracking for Rapid Deterioration
        prev_health = strat["current_health_score"]
        strat["previous_health_score"] = prev_health
        strat["current_health_score"] = health_score
        strat["last_classification"] = drift_res["classification"]
        
        alerts = []
        
        # Rule 1: Static Thresholds
        if health_score < cfg["health_critical_threshold"]:
            alerts.append({"type": "CRITICAL", "message": f"Health Score below CRITICAL threshold ({health_score:.1f}/100)"})
        elif health_score < cfg["health_warning_threshold"]:
            alerts.append({"type": "WARNING", "message": f"Health Score below WARNING threshold ({health_score:.1f}/100)"})
            
        # Rule 2: Rapid Deterioration (Drift Velocity)
        if (prev_health - health_score) >= cfg["deterioration_warning_drop"]:
            alerts.append({
                "type": "WARNING", 
                "message": f"Rapid Deterioration Detected: Health dropped {prev_health - health_score:.1f} points instantly."
            })
            
        strat["active_alerts"] = alerts
        
        return {
            "strategy_id": strategy_id,
            "status": drift_res["classification"],
            "health_score": health_score,
            "drift_z_score": z_score,
            "recent_metrics": drift_res.get("recent_metrics", {}),
            "alerts": alerts
        }

    async def check_all_strategies(self) -> List[dict]:
        """
        Iterates and evaluates health across all registered strategies.
        Returns a list of payloads ONLY for strategies with active warnings or critical alerts.
        Also dispatches alerts via AlertManager if available.
        """
        triggered_alerts = []
        for strat_id in list(self.strategies.keys()):
            res = self.evaluate_strategy_health(strat_id)
            if res and res.get("alerts"):
                triggered_alerts.append(res)
                
                # Dispatch to AlertManager if present
                if self.alert_manager:
                    for alert in res["alerts"]:
                        severity = alert["type"] # WARNING or CRITICAL
                        await self.alert_manager.send_alert(
                            strategy_id=strat_id,
                            message=alert["message"],
                            severity=severity,
                            metadata={
                                "health_score": res["health_score"],
                                "status": res["status"]
                            }
                        )
                
        return triggered_alerts
