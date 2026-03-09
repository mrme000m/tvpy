#!/usr/bin/env python3
"""
Single Indicator Test
=====================

Simple test script to verify indicator functionality.
Run this after waiting a few minutes from any previous indicator tests
to avoid the "maximum number of studies" free tier limit.

Usage:
    python test_single_indicator.py [indicator_id]

Examples:
    python test_single_indicator.py STD;SMA
    python test_single_indicator.py STD;RSI
    python test_single_indicator.py STD;MACD
"""

import asyncio
import os
import sys
from pathlib import Path

# Load .env file
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()

from tradingview import Client, get_indicator


async def test_indicator(indicator_id: str = "STD;SMA"):
    """Test a single indicator."""
    
    session = os.environ.get('SESSION')
    signature = os.environ.get('SIGNATURE')
    
    print(f"Fetching indicator: {indicator_id}")
    try:
        indic = await get_indicator(indicator_id, session=session, signature=signature)
        print(f"  -> Got: {indic.pine_id}")
        print(f"  -> Description: {indic.description}")
        print(f"  -> Inputs: {list(indic.inputs.keys())[:5]}...")
        print(f"  -> Plots: {indic.plots}")
    except Exception as e:
        print(f"  -> ERROR: {e}")
        return
    
    print("\nConnecting to TradingView...")
    client = Client(session=session, signature=signature)
    
    def on_client_error(err):
        print(f"  Client error: {err}")
    
    client.on_error(on_client_error)
    await client.connect()
    print("  -> Connected!")
    
    print("\nCreating chart...")
    chart = client.Session.Chart()
    chart.set_market('BINANCE:BTCUSDT', timeframe='60', range=100)
    
    # Wait for chart data
    chart_future = asyncio.Future()
    def on_chart_update(changes):
        if chart.periods and not chart_future.done():
            chart_future.set_result(True)
    chart.on_update(on_chart_update)
    
    try:
        await asyncio.wait_for(chart_future, timeout=15)
        print(f"  -> Chart ready with {len(chart.periods)} periods")
    except asyncio.TimeoutError:
        print("  -> Timeout waiting for chart data")
        await client.end()
        return
    
    print("\nCreating study...")
    study = chart.Study(indic)
    
    study_future = asyncio.Future()
    success = False
    error_msg = None
    
    def on_study_update(changes):
        nonlocal success
        if study.periods and not study_future.done():
            success = True
            study_future.set_result(True)
    
    def on_study_error(err):
        nonlocal error_msg
        error_msg = str(err)
        print(f"  Study error: {err}")
        if not study_future.done():
            study_future.set_result(False)
    
    study.on_update(on_study_update)
    study.on_error(on_study_error)
    
    print("  Waiting for study data...")
    try:
        await asyncio.wait_for(study_future, timeout=20)
        
        if success:
            print(f"  -> SUCCESS! Got {len(study.periods)} periods")
            if study.periods:
                print(f"\n  Sample data (last period):")
                last = study.periods[0]
                for k, v in last.items():
                    if not k.startswith('$'):
                        print(f"    {k}: {v}")
            study.remove()
        else:
            print(f"  -> FAILED: {error_msg or 'Unknown error'}")
            if 'maximum number of studies' in (error_msg or '').lower():
                print("\n  NOTE: You've hit the free tier study limit.")
                print("  Wait a few minutes before trying again.")
    except asyncio.TimeoutError:
        print("  -> Timeout waiting for study data")
        study.remove()
    
    chart.delete()
    await client.end()
    print("\nDone!")


if __name__ == '__main__':
    indicator_id = sys.argv[1] if len(sys.argv) > 1 else "STD;SMA"
    asyncio.run(test_indicator(indicator_id))
