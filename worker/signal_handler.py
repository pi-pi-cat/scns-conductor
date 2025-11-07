"""
信号处理器
"""
import signal
from typing import Callable, List, Optional
from loguru import logger


class SignalHandler:
    """
    优雅的信号处理器
    
    支持多个回调函数和链式调用
    
    使用示例:
        handler = SignalHandler()
        handler.on_shutdown(lambda: logger.info("Cleaning up..."))
        handler.on_shutdown(worker.stop)
        handler.on_shutdown(daemon.stop)
        handler.register()  # 注册信号处理
        
        # 链式调用
        SignalHandler() \\
            .on_shutdown(daemon.stop) \\
            .on_shutdown(worker.request_stop) \\
            .register()
    """
    
    def __init__(self):
        self._shutdown_callbacks: List[Callable] = []
        self._original_handlers = {}
    
    def on_shutdown(self, callback: Callable) -> "SignalHandler":
        """
        添加关闭回调
        
        Args:
            callback: 关闭时调用的函数
        
        Returns:
            self (支持链式调用)
        """
        self._shutdown_callbacks.append(callback)
        return self
    
    def register(self, signals: Optional[List[int]] = None) -> None:
        """
        注册信号处理器
        
        Args:
            signals: 要处理的信号列表（默认：SIGTERM, SIGINT）
        """
        if signals is None:
            signals = [signal.SIGTERM, signal.SIGINT]
        
        def handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info(f"🛑 Received {sig_name}, initiating graceful shutdown...")
            
            # 执行所有关闭回调
            for callback in self._shutdown_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"❌ Error in shutdown callback: {e}")
        
        # 保存原始处理器并注册新处理器
        for sig in signals:
            self._original_handlers[sig] = signal.signal(sig, handler)
            logger.debug(f"✅ Registered handler for {signal.Signals(sig).name}")
    
    def restore(self) -> None:
        """恢复原始信号处理器"""
        for sig, original_handler in self._original_handlers.items():
            signal.signal(sig, original_handler)
        self._original_handlers.clear()

