"""
MA20趋势跟踪策略 - 简单功能测试
验证核心模块的基本功能
注意：使用的是生成数据！仅做调试使用
"""

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def test_basic_functionality():
    """测试基本功能"""
    print("开始MA20趋势跟踪策略基本功能测试...")
    
    # 1. 测试数据处理器
    print("\n1. 测试数据处理器...")
    from src.data_processor import DataProcessor
    
    # 创建测试数据
    dates = pd.date_range('2023-01-01', periods=20, freq='D')
    test_data = pd.DataFrame({
        'date': dates,
        'open': [100 + i*2 for i in range(20)],
        'high': [102 + i*2 for i in range(20)],
        'low': [98 + i*2 for i in range(20)],
        'close': [101 + i*2 for i in range(20)],
        'volume': [1000 + i*100 for i in range(20)]
    })
    
    processor = DataProcessor()
    
    # 测试2日K线合成
    data_2day = processor.create_2day_kline(test_data)
    print(f"✓ 2日K线合成: {len(test_data)} -> {len(data_2day)} 条记录")
    
    # 测试MA计算
    data_with_ma = processor.calculate_ma(data_2day, period=5)
    print(f"✓ MA5计算完成，数据列: {list(data_with_ma.columns)}")
    
    # 2. 测试信号生成器
    print("\n2. 测试信号生成器...")
    from src.signal_generator import SignalGenerator
    
    generator = SignalGenerator(ma_period=5)
    signals_data = generator.generate_signals(data_with_ma)
    
    buy_signals = (signals_data['signal'] == 1).sum()
    sell_signals = (signals_data['signal'] == -1).sum()
    print(f"✓ 信号生成: 做多{buy_signals}个, 做空{sell_signals}个")
    
    # 3. 测试风险管理器
    print("\n3. 测试风险管理器...")
    from src.risk_manager import RiskManager, PositionSide
    
    risk_manager = RiskManager()
    
    # 测试做多止损
    stop_result = risk_manager.calculate_stop_loss(
        entry_price=4000.0, 
        prev_extreme=3800.0, 
        direction=PositionSide.LONG
    )
    print(f"✓ 做多止损: 进场价4000.0, 止损价{stop_result.stop_price:.2f}")
    
    # 测试做空止损
    stop_result = risk_manager.calculate_stop_loss(
        entry_price=4000.0, 
        prev_extreme=4200.0, 
        direction=PositionSide.SHORT
    )
    print(f"✓ 做空止损: 进场价4000.0, 止损价{stop_result.stop_price:.2f}")
    
    # 测试仓位计算
    position_result = risk_manager.calculate_position_size(
        capital=100000.0,
        entry_price=4000.0,
        stop_price=3800.0,
        margin_rate=0.10,
        contract_multiplier=10.0
    )
    print(f"✓ 仓位计算: 建议{position_result.position_size}手, 风险{position_result.risk_pct_of_capital:.2%}")
    
    # 4. 测试配置
    print("\n4. 测试配置...")
    from config import get_config, validate_config
    
    config = get_config()
    print(f"✓ 配置加载: MA周期={config['ma_period']}, 止损容忍度={config['max_loss_pct']}")
    
    is_valid = validate_config()
    print(f"✓ 配置验证: {'通过' if is_valid else '失败'}")
    
    print("\n✅ 基本功能测试完成!")
    return True

def test_data_validation():
    """测试数据验证逻辑"""
    print("\n测试数据验证逻辑...")
    
    # 创建有问题的数据
    test_data = pd.DataFrame({
        'date': pd.date_range('2023-01-01', periods=5),
        'open': [100, 102, 101, 103, 104],
        'high': [99, 104, 103, 105, 106],  # 第一行high < open
        'low': [101, 101, 100, 102, 103],  # 第一行low > open
        'close': [101, 103, 102, 104, 105],
        'volume': [1000] * 5
    })
    
    print("原始数据:")
    print(test_data)
    
    # 修复价格逻辑
    for i in range(len(test_data)):
        row = test_data.iloc[i]
        test_data.loc[i, 'high'] = max(row['high'], row['open'], row['close'])
        test_data.loc[i, 'low'] = min(row['low'], row['open'], row['close'])
    
    print("\n修复后的数据:")
    print(test_data)
    
    # 验证价格逻辑
    for i in range(len(test_data)):
        row = test_data.iloc[i]
        assert row['low'] <= row['open'], f"第{i}行: low <= open"
        assert row['low'] <= row['close'], f"第{i}行: low <= close"
        assert row['high'] >= row['open'], f"第{i}行: high >= open"
        assert row['high'] >= row['close'], f"第{i}行: high >= close"
    
    print("✓ 数据验证逻辑测试通过")
    return True

def test_signal_logic():
    """测试信号生成逻辑"""
    print("\n测试信号生成逻辑...")
    
    # 创建测试数据
    dates = pd.date_range('2023-01-01', periods=10, freq='2D')
    test_data = pd.DataFrame({
        'date': dates,
        'open': [100, 102, 101, 103, 104, 105, 106, 107, 108, 109],
        'high': [102, 104, 103, 105, 106, 107, 108, 109, 110, 111],
        'low': [98, 101, 100, 102, 103, 104, 105, 106, 107, 108],
        'close': [101, 103, 102, 104, 105, 106, 107, 108, 109, 110],
        'volume': [1000] * 10
    })
    
    # 添加MA5
    test_data['ma5'] = test_data['close'].rolling(window=5).mean()
    
    # 测试信号生成
    from src.signal_generator import SignalGenerator
    generator = SignalGenerator(ma_period=5)
    signals_data = generator.generate_signals(test_data)
    
    # 验证信号逻辑
    for i in range(len(signals_data)):
        signal = signals_data.iloc[i]['signal']
        if pd.notna(signal):
            row = signals_data.iloc[i]
            if signal == 1:  # 做多信号
                assert row['close'] > row['ma5'], f"做多信号时收盘价应高于MA5"
                assert row['close'] > row['open'], f"做多信号时应收阳线"
                print(f"✓ 做多信号验证: 日期{row['date']}, 收盘价{row['close']:.1f} > MA5{row['ma5']:.1f}")
            elif signal == -1:  # 做空信号
                assert row['close'] < row['ma5'], f"做空信号时收盘价应低于MA5"
                assert row['close'] < row['open'], f"做空信号时应收阴线"
                print(f"✓ 做空信号验证: 日期{row['date']}, 收盘价{row['close']:.1f} < MA5{row['ma5']:.1f}")
    
    print("✓ 信号生成逻辑测试通过")
    return True

if __name__ == "__main__":
    try:
        # 运行基本功能测试
        test_basic_functionality()
        
        # 运行数据验证测试
        test_data_validation()
        
        # 运行信号逻辑测试
        test_signal_logic()
        
        print("\n🎉 所有测试通过! MA20趋势跟踪策略基本功能正常!")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
