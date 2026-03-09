#!/usr/bin/env python3
"""
Example: Study Management on Chart Session
==========================================

Demonstrates how to:
1. Check active studies on a chart
2. Remove individual studies by ID
3. Remove all studies at once

This is essential for free tier users who need to manage the 1-2 study limit.

Usage:
    python example_study_management.py
"""

import asyncio
import os
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


async def main():
    """Demonstrate study management."""
    
    session = os.environ.get('SESSION')
    signature = os.environ.get('SIGNATURE')
    
    print("=" * 60)
    print("STUDY MANAGEMENT EXAMPLE")
    print("=" * 60)
    print()
    
    # Create client
    print("1. Connecting to TradingView...")
    client = Client(session=session, signature=signature)
    await client.connect()
    print("   Connected!\n")
    
    # Create chart
    print("2. Creating chart...")
    chart = client.Session.Chart()
    chart.set_market('BINANCE:BTCUSDT', timeframe='60', range=50)
    
    # Wait for chart
    chart_ready = asyncio.Future()
    def on_ready(changes):
        if chart.periods and not chart_ready.done():
            chart_ready.set_result(True)
    chart.on_update(on_ready)
    
    try:
        await asyncio.wait_for(chart_ready, timeout=15)
        print(f"   Chart ready with {len(chart.periods)} periods\n")
    except asyncio.TimeoutError:
        print("   Chart timeout (continuing anyway)\n")
    
    # Check studies (should be empty)
    print("3. Checking active studies...")
    studies = chart.get_studies()
    print(f"   Active studies: {len(studies)}")
    if studies:
        for s in studies:
            print(f"     - {s['id']}")
    print()
    
    # Add some studies
    print("4. Adding studies...")
    study_objects = []
    
    for ind_id, name in [('STD;SMA', 'SMA'), ('STD;RSI', 'RSI')]:
        try:
            indicator = await get_indicator(ind_id, session=session, signature=signature)
            study = chart.Study(indicator)
            study_objects.append((name, study))
            print(f"   Added {name}: {study._stud_id}")
            await asyncio.sleep(1)  # Brief pause
        except Exception as e:
            print(f"   Error adding {name}: {e}")
    
    print()
    
    # Check studies again
    print("5. Checking active studies...")
    studies = chart.get_studies()
    print(f"   Active studies: {len(studies)}")
    for s in studies:
        print(f"     - {s['id']}")
    print()
    
    # Remove first study
    if study_objects:
        name, study = study_objects[0]
        print(f"6. Removing {name} ({study._stud_id})...")
        
        # Method 1: Use study.remove()
        study.remove()
        print(f"   Removed via study.remove()")
        
        # Verify
        await asyncio.sleep(0.5)
        studies = chart.get_studies()
        print(f"   Remaining studies: {len(studies)}\n")
    
    # Remove all remaining studies
    if len(study_objects) > 1:
        print("7. Removing all remaining studies...")
        removed = await chart.remove_all_studies()
        print(f"   Removed {removed} studies\n")
    
    # Final check
    print("8. Final study count...")
    studies = chart.get_studies()
    print(f"   Active studies: {len(studies)}")
    print()
    
    # Cleanup
    print("9. Cleanup...")
    chart.delete()
    await client.end()
    print("   Done!")
    
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("""
ChartSession methods for study management:

  1. chart.get_studies()
     Returns: [{'id': 'st_abc123'}, ...]
     
  2. chart.remove_study('st_abc123')
     Removes specific study by ID
     Returns: True if found/removed, False otherwise
     
  3. await chart.remove_all_studies()
     Removes all studies at once
     Returns: Number of studies removed

These are useful when:
- You need to check if you've hit the study limit
- You want to clean up studies without deleting the chart
- You're managing studies dynamically

Note: For free tier users, it's often easier to just call:
  chart.delete()  # Removes everything
  chart = client.Session.Chart()  # Create fresh chart
""")


if __name__ == '__main__':
    asyncio.run(main())
