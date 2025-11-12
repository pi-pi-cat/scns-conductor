#!/usr/bin/env python3
"""
自动注册机制演示脚本

展示 __init_subclass__ 如何实现策略的自动注册
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def demo_registry():
    """演示策略注册表"""
    print("=" * 80)
    print("🔍 查看已注册的清理策略（自动注册）")
    print("=" * 80)

    strategies = get_registered_strategies()

    print(f"\n✅ 共注册 {len(strategies)} 个策略类:\n")

    for i, (key, cls) in enumerate(strategies.items(), 1):
        print(f"  {i}. {key}")
        print(f"     └─ 类: {cls.__module__}.{cls.__qualname__}")
        print(f"     └─ 文档: {cls.__doc__.strip() if cls.__doc__ else 'N/A'}")
        print()


def demo_manager_creation():
    """演示管理器创建和策略实例化"""
    print("=" * 80)
    print("🏗️  创建清理策略管理器（自动加载所有策略）")
    print("=" * 80)

    manager = create_default_manager()

    print(f"\n✅ 管理器已创建，包含 {len(manager.strategies)} 个策略实例:\n")

    for i, (name, strategy) in enumerate(manager.strategies.items(), 1):
        print(f"  {i}. [{name}]")
        print(f"     └─ 描述: {strategy.description}")
        print(f"     └─ 执行间隔: {strategy.interval_seconds}秒")
        print(f"     └─ 启用状态: {'✅ 启用' if strategy.enabled else '❌ 禁用'}")
        print()


def demo_custom_strategy():
    """演示自定义策略的自动注册"""
    print("=" * 80)
    print("✨ 演示：定义新策略时自动注册")
    print("=" * 80)

    # 获取注册前的数量
    from scheduler.cleanup_strategies import get_registered_strategies

    before_count = len(get_registered_strategies())

    print(f"\n📊 注册前: {before_count} 个策略\n")

    # 定义一个新策略（会自动注册）
    from scheduler.cleanup_strategies import BaseCleanupStrategy

    class DemoCleanupStrategy(BaseCleanupStrategy):
        """演示用的清理策略"""

        @property
        def name(self):
            return "demo_cleanup"

        @property
        def description(self):
            return "这是一个演示策略（自动注册）"

        def _do_cleanup(self, session):
            print("      [执行演示清理...]")
            return 0

    # 获取注册后的数量
    after_count = len(get_registered_strategies())

    print(f"📊 注册后: {after_count} 个策略\n")

    if after_count > before_count:
        print("✅ 策略已自动注册！（无需调用 register）\n")

        # 验证是否真的注册了
        strategies = get_registered_strategies()
        if "DemoCleanupStrategy" in strategies:
            print(f"🎉 验证成功: DemoCleanupStrategy 在注册表中")
            print(f"   └─ 类: {strategies['DemoCleanupStrategy']}")
        else:
            print("❌ 验证失败: 未找到 DemoCleanupStrategy")
    else:
        print("❌ 注册失败")


def main():
    """主函数"""
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "自动注册机制演示" + " " * 38 + "║")
    print("║" + " " * 15 + "(__init_subclass__ Magic)" + " " * 38 + "║")
    print("╚" + "═" * 78 + "╝")
    print("\n")

    try:
        from scheduler.cleanup_strategies import (
            get_registered_strategies,
            create_default_manager,
        )

        # 1. 展示已注册的策略类
        demo_registry()

        # 2. 展示管理器创建和策略实例化
        demo_manager_creation()

        # 3. 展示自定义策略的自动注册
        demo_custom_strategy()

        print("=" * 80)
        print("🎓 关键点总结")
        print("=" * 80)
        print()
        print("1. ✅ 策略类定义时自动注册（无需手动调用 register）")
        print("2. ✅ 使用 __init_subclass__ 实现（比元类更简洁）")
        print("3. ✅ 只注册非抽象的具体类（自动过滤基类）")
        print("4. ✅ 管理器通过 auto_register_all() 批量加载所有策略")
        print("5. ✅ 新增策略零侵入（只需定义类即可）")
        print()
        print("📚 详细文档: docs/AUTO_REGISTRATION.md")
        print()
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        print("\n提示: 请确保在项目根目录运行或安装必要的依赖")
        sys.exit(1)


if __name__ == "__main__":
    main()
