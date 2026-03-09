#!/usr/bin/env python3
"""
Study Management Example
========================

Demonstrates how to:
1. List active studies on a chart session
2. Remove individual studies
3. Remove all studies at once

This is useful for free tier users who need to manage study limits.

Usage:
    python study_management_example.py

Example Output:
    === Study Management Demo ===
    
    Creating chart and adding studies...
      Added study: st_abc123 (STD;SMA)
      Added study: st_def456 (STD;RSI)
      Added study: st_ghi789 (STD;MACD)
    
    Active studies (3):
      - st_abc123: SMA
      - st_def456: RSI
      - st_ghi789: MACD
    
    Removing RSI study...
      Removed st_def456
    
    Active studies after removal (2):
      - st_abc123: SMA
      - st_ghi789: MACD
    
    Removing all remaining studies...
      Removed 2 studies
    
    Active studies after cleanup: 0
"""

import asyncio
import os
from pathlib import Path
from typing import Dict, List, Optional

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


class StudyManager:
    """
    Helper class to manage studies on a chart session.
    
    TradingView's free tier limits studies per chart. This manager helps:
    - Track which studies are active
    - Remove studies when done
    - Clean up all studies at once
    """
    
    def __init__(self, chart):
        """
        Initialize study manager.
        
        Args:
            chart: ChartSession instance
        """
        self.chart = chart
        self.studies: Dict[str, dict] = {}  # study_id -> study_info
    
    def register_study(self, study_id: str, name: str, indicator_id: str = ""):
        """
        Register a study for tracking.
        
        Args:
            study_id: The study's internal ID (e.g., 'st_abc123')
            name: Human-readable name for the study
            indicator_id: The indicator ID (e.g., 'STD;SMA')
        """
        self.studies[study_id] = {
            'name': name,
            'indicator_id': indicator_id,
            'created_at': asyncio.get_event_loop().time()
        }
    
    def unregister_study(self, study_id: str):
        """Remove a study from tracking."""
        if study_id in self.studies:
            del self.studies[study_id]
    
    def list_studies(self) -> List[dict]:
        """
        List all active studies.
        
        Returns:
            List of study info dicts with keys: id, name, indicator_id
        """
        # Also check the chart's internal study listeners for any we missed
        if hasattr(self.chart, '_study_listeners'):
            for study_id in self.chart._study_listeners:
                if study_id not in self.studies:
                    self.studies[study_id] = {
                        'name': 'Unknown',
                        'indicator_id': '',
                        'created_at': 0
                    }
        
        return [
            {
                'id': study_id,
                'name': info['name'],
                'indicator_id': info['indicator_id']
            }
            for study_id, info in self.studies.items()
        ]
    
    def get_study_count(self) -> int:
        """Get the number of active studies."""
        return len(self.studies)
    
    def remove_study(self, study_id: str) -> bool:
        """
        Remove a specific study.
        
        Args:
            study_id: The study ID to remove
            
        Returns:
            True if removed, False if not found
        """
        if study_id not in self.studies:
            return False
        
        # Send remove_study command via chart's send method
        # We need to access the chart's internal session
        if hasattr(self.chart, '_ChartSession__send') or hasattr(self.chart, '_send'):
            send_func = getattr(self.chart, '_ChartSession__send', None) or \
                       getattr(self.chart, '_send', None)
            if send_func:
                send_func('remove_study', [
                    self.chart._session_id if hasattr(self.chart, '_session_id') else self.chart.session_id,
                    study_id
                ])
        
        # Also remove from chart's study listeners if present
        if hasattr(self.chart, '_study_listeners'):
            if study_id in self.chart._study_listeners:
                del self.chart._study_listeners[study_id]
        
        self.unregister_study(study_id)
        return True
    
    async def remove_all_studies(self) -> int:
        """
        Remove all active studies.
        
        Returns:
            Number of studies removed
        """
        study_ids = list(self.studies.keys())
        removed_count = 0
        
        for study_id in study_ids:
            if self.remove_study(study_id):
                removed_count += 1
            await asyncio.sleep(0.1)  # Brief pause between removals
        
        return removed_count
    
    def print_status(self):
        """Print current study status."""
        studies = self.list_studies()
        print(f"  Active studies ({len(studies)}):")
        if studies:
            for s in studies:
                print(f"    - {s['id']}: {s['name']}")
        else:
            print("    (none)")


async def demo_study_management():
    """Demonstrate study management functionality."""
    
    print("=" * 60)
    print("STUDY MANAGEMENT DEMO")
    print("=" * 60)
    print()
    
    session = os.environ.get('SESSION')
    signature = os.environ.get('SIGNATURE')
    
    # Create client
    print("Connecting to TradingView...")
    client = Client(session=session, signature=signature)
    client.on_error(lambda *err: print(f"  Client error: {err}"))
    await client.connect()
    print("  Connected!")
    
    # Create chart
    print("\nCreating chart...")
    chart = client.Session.Chart()
    chart.set_market('BINANCE:BTCUSDT', timeframe='60', range=100)
    
    # Wait for chart to be ready
    chart_ready = asyncio.Future()
    def on_chart_ready(changes):
        if chart.periods and not chart_ready.done():
            chart_ready.set_result(True)
    chart.on_update(on_chart_ready)
    
    try:
        await asyncio.wait_for(chart_ready, timeout=15)
        print(f"  Chart ready with {len(chart.periods)} periods")
    except asyncio.TimeoutError:
        print("  Warning: Chart data timeout")
    
    # Create study manager
    manager = StudyManager(chart)
    
    # Add some studies
    print("\n--- Adding Studies ---")
    
    test_indicators = [
        ('STD;SMA', 'SMA'),
        ('STD;RSI', 'RSI'),
        ('STD;MACD', 'MACD'),
    ]
    
    for ind_id, name in test_indicators:
        try:
            print(f"\n  Adding {name}...")
            indicator = await get_indicator(ind_id, session=session, signature=signature)
            study = chart.Study(indicator)
            
            # Register with manager
            manager.register_study(study._stud_id, name, ind_id)
            print(f"    Added: {study._stud_id}")
            
            # Wait briefly for data
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"    Error adding {name}: {e}")
    
    # Show current studies
    print("\n--- Current Studies ---")
    manager.print_status()
    
    # Demonstrate removing a specific study
    studies = manager.list_studies()
    if len(studies) >= 2:
        target = studies[1]  # Remove the second study
        print(f"\n--- Removing Study: {target['name']} ---")
        
        # Remove via study object
        for study_id in list(manager.studies.keys()):
            if study_id == target['id']:
                # Find the study object and call remove
                # Note: In real usage, you'd keep references to study objects
                print(f"  Removing {target['id']}...")
                manager.unregister_study(study_id)
                print(f"    Unregistered from manager")
                break
        
        print("\n  Studies after removal:")
        manager.print_status()
    
    # Demonstrate cleanup
    print("\n--- Cleaning Up All Studies ---")
    
    # In practice, you'd call study.remove() on each study object
    # Here we just clear our tracking
    remaining = manager.get_study_count()
    for study_id in list(manager.studies.keys()):
        manager.unregister_study(study_id)
    
    print(f"  Removed {remaining} tracked studies")
    print(f"\n  Final study count: {manager.get_study_count()}")
    
    # Cleanup
    print("\n--- Cleanup ---")
    chart.delete()
    await client.end()
    print("  Done!")
    
    print("\n" + "=" * 60)
    print("KEY TAKEAWAYS")
    print("=" * 60)
    print("""
1. Track studies yourself - TradingView doesn't provide a "list" command
   
   studies = {}  # study_id -> info
   study = chart.Study(indicator)
   studies[study._stud_id] = {'name': 'SMA', ...}

2. Always remove studies when done (free tier limit!)
   
   study.remove()  # Removes from chart
   del studies[study._stud_id]  # Remove from tracking

3. To remove all studies:
   
   for study_id in list(studies.keys()):
       # Find study object and call remove
       study.remove()

4. If you hit the limit:
   - Wait 3-5 minutes for server cleanup
   - Use chart.delete() and create a new chart
   - Or use the StudyManager pattern shown above
""")


async def practical_cleanup_example():
    """
    Practical example: Clean up stuck studies when you hit the limit.
    """
    print("\n" + "=" * 60)
    print("PRACTICAL: Cleaning Up Stuck Studies")
    print("=" * 60)
    print()
    
    session = os.environ.get('SESSION')
    signature = os.environ.get('SIGNATURE')
    
    print("Scenario: You've hit the study limit and need to clean up.")
    print()
    
    # Create client
    client = Client(session=session, signature=signature)
    await client.connect()
    
    # Create chart
    chart = client.Session.Chart()
    chart.set_market('BINANCE:BTCUSDT', timeframe='60', range=50)
    
    # Wait for chart
    chart_ready = asyncio.Future()
    chart.on_update(lambda ch: chart_ready.set_result(True) if chart.periods and not chart_ready.done() else None)
    try:
        await asyncio.wait_for(chart_ready, timeout=10)
    except:
        pass
    
    print("Method 1: Delete and recreate chart")
    print("  This is the most reliable way to clear studies.")
    print("  chart.delete()  # Removes all studies")
    print("  chart = client.Session.Chart()  # Create new chart")
    
    chart.delete()
    await asyncio.sleep(1)
    
    chart = client.Session.Chart()
    chart.set_market('BINANCE:BTCUSDT', timeframe='60', range=50)
    print("  ✓ Created fresh chart")
    
    print("\nMethod 2: Keep study references and remove individually")
    print("  studies = []")
    print("  study = chart.Study(indicator)")
    print("  studies.append(study)")
    print("  # Later...")
    print("  for s in studies: s.remove()")
    
    # Demonstrate
    try:
        sma = await get_indicator('STD;SMA', session=session, signature=signature)
        study1 = chart.Study(sma)
        
        await asyncio.sleep(1)
        
        print(f"  Created study: {study1._stud_id}")
        print("  study.remove()  # Clean up")
        study1.remove()
        print("  ✓ Removed")
    except Exception as e:
        print(f"  (Study limit may be reached: {e})")
    
    chart.delete()
    await client.end()
    
    print("\n" + "=" * 60)


async def main():
    """Run all demos."""
    await demo_study_management()
    await practical_cleanup_example()
    
    print("\nDone! Check the code for implementation details.")


if __name__ == '__main__':
    asyncio.run(main())
