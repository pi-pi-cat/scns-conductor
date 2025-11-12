"""
策略配置加载
"""

from pathlib import Path
from typing import List, Optional

from loguru import logger

from .base import get_strategy_registry
from .manager import CleanupStrategyManager
from .metadata import StrategyMetadata
from .observers import StrategyObserver


def load_strategy_config(config_path: Path) -> dict:
    """
    从 YAML 配置文件加载策略配置

    Args:
        config_path: 配置文件路径

    Returns:
        配置字典
    """
    try:
        import yaml

        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except ImportError:
        logger.warning("PyYAML not installed, cannot load YAML config")
        return {}
    except Exception as e:
        logger.error(f"Failed to load config from {config_path}: {e}")
        return {}


def create_manager_from_config(
    config_path: Optional[Path] = None,
    observers: List[StrategyObserver] = None,
) -> CleanupStrategyManager:
    """
    从配置文件创建管理器

    Args:
        config_path: 配置文件路径（None 时使用默认配置）
        observers: 观察者列表

    Returns:
        策略管理器实例
    """
    manager = CleanupStrategyManager(observers=observers)

    if config_path and config_path.exists():
        config = load_strategy_config(config_path)
        strategy_configs = config.get("strategies", {})

        # 从配置加载策略
        _strategy_registry = get_strategy_registry()
        for registry_key, strategy_cls in _strategy_registry.items():
            strategy_name = getattr(strategy_cls, "_registry_key", None) or registry_key

            if strategy_name in strategy_configs:
                config_data = strategy_configs[strategy_name]
                kwargs = config_data.copy()

                # 创建实例并注册
                strategy = strategy_cls(**kwargs)
                manager.register(strategy)
            else:
                # 使用默认配置
                metadata = getattr(strategy_cls, "_metadata", StrategyMetadata())
                if metadata.enabled_by_default:
                    strategy = strategy_cls()
                    manager.register(strategy)
    else:
        # 使用默认配置
        manager.auto_register_all()

    return manager


def create_default_manager(
    observers: List[StrategyObserver] = None,
) -> CleanupStrategyManager:
    """
    创建带有默认策略的管理器

    Args:
        observers: 观察者列表（默认包含 LoggingObserver）

    Returns:
        策略管理器实例
    """
    from .strategies import (
        CompletedJobCleanupStrategy,
        OldJobCleanupStrategy,
        StaleReservationCleanupStrategy,
        StuckJobCleanupStrategy,
    )

    manager = CleanupStrategyManager(observers=observers)

    # 自动注册所有策略，并传入各自的配置参数
    manager.auto_register_all(
        StaleReservationCleanupStrategy={
            "interval_seconds": 120,
            "max_age_minutes": 10,
        },
        CompletedJobCleanupStrategy={
            "interval_seconds": 5,
        },
        StuckJobCleanupStrategy={
            "interval_seconds": 3600,
            "max_age_hours": 48,
        },
        OldJobCleanupStrategy={
            "interval_seconds": 86400,
            "max_age_days": 30,
            "enabled": False,  # 默认禁用
        },
    )

    return manager


def get_registered_strategies():
    """获取所有已注册的策略类（用于调试）"""
    return get_strategy_registry().copy()

