"""
时间格式化和解析工具
"""
from datetime import datetime, timedelta
from typing import Optional


def format_elapsed_time(start_time: datetime, end_time: Optional[datetime] = None) -> str:
    """
    以Slurm风格格式化经过的时间：day-HH:MM:SS
    
    Args:
        start_time: 开始时间
        end_time: 结束时间（未提供时默认为当前时间）
    
    Returns:
        格式化字符串，如 "0-00:39:20" 或 "2-14:30:45"
    """
    if end_time is None:
        end_time = datetime.utcnow()
    
    delta = end_time - start_time
    days = delta.days
    seconds = delta.seconds
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    return f"{days}-{hours:02d}:{minutes:02d}:{secs:02d}"


def format_limit_time(minutes: int) -> str:
    """
    将时间限制从分钟格式化为 HH:MM:SS 或 D-HH:MM:SS
    
    Args:
        minutes: 以分钟为单位的时间限制
    
    Returns:
        格式化字符串，如 "2:00:00" 或 "1-12:30:00"
    """
    if minutes < 0:
        return "UNLIMITED"
    
    total_seconds = minutes * 60
    days = total_seconds // 86400
    remaining_seconds = total_seconds % 86400
    
    hours = remaining_seconds // 3600
    mins = (remaining_seconds % 3600) // 60
    secs = remaining_seconds % 60
    
    if days > 0:
        return f"{days}-{hours:02d}:{mins:02d}:{secs:02d}"
    else:
        return f"{hours}:{mins:02d}:{secs:02d}"


def parse_time_limit(time_str: str) -> int:
    """
    解析时间限制字符串为分钟数
    
    支持的格式：
        - "30" -> 30分钟
        - "2:30" -> 2小时30分钟
        - "1:30:00" -> 1小时30分钟
        - "2-12:00:00" -> 2天12小时
    
    Args:
        time_str: 时间限制字符串
    
    Returns:
        以分钟为单位的时间限制
    """
    time_str = time_str.strip()
    
    # Simple number (minutes)
    if time_str.isdigit():
        return int(time_str)
    
    # Contains day separator
    if '-' in time_str:
        days_part, time_part = time_str.split('-', 1)
        days = int(days_part)
        parts = time_part.split(':')
    else:
        days = 0
        parts = time_str.split(':')
    
    # Parse time parts
    if len(parts) == 1:
        # Just hours
        hours = int(parts[0])
        mins = 0
    elif len(parts) == 2:
        # Hours:Minutes
        hours = int(parts[0])
        mins = int(parts[1])
    elif len(parts) == 3:
        # Hours:Minutes:Seconds
        hours = int(parts[0])
        mins = int(parts[1])
        # Ignore seconds for minute-based calculation
    else:
        raise ValueError(f"Invalid time format: {time_str}")
    
    total_minutes = days * 24 * 60 + hours * 60 + mins
    return total_minutes

