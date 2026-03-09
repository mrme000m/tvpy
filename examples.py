"""
TradingView API Examples - Python Implementation

This file contains Python equivalents of the JavaScript examples from tvjs/examples/:
- SimpleChart: Basic chart with price updates
- BuiltInIndicator: Volume profile indicator
- AllPrivateIndicators: Load all user's private indicators
- FetchHistoricalData: Fetch historical OHLCV data and save to CSV
- ListSavedPineScripts: List saved/private Pine scripts
- Search: Search for markets and indicators

Usage:
    python examples.py [example_name] [--session SESSION] [--signature SIGNATURE]

Examples:
    python examples.py simple_chart
    python examples.py builtin_indicator
    python examples.py all_private_indicators
    python examples.py fetch_historical_data --count 500
    python examples.py list_saved_scripts --json
    python examples.py search
    python examples.py all  # Run all examples sequentially
"""

import asyncio
import json
import os
import sys
import csv
from datetime import datetime
from typing import Optional, Dict, List, Any

# Load .env file explicitly
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If python-dotenv is not installed, try to load .env manually
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

# Load tradingview module
from tradingview import (
    Client,
    ChartSession,
    QuoteSession,
    PineIndicator,
    BuiltInIndicator,
    PineFacadeClient,
    get_indicator,
    get_private_indicators,
    search_market_v3,
    search_indicator,
    login_user,
    gen_auth_cookies,
    set_debug,
)


# ============================================================================
# CONFIGURATION
# ============================================================================

def load_config():
    """Load configuration from .env file and CLI arguments."""
    # Default values from .env
    session = os.environ.get('SESSION', '')
    signature = os.environ.get('SIGNATURE', '')
    tv_user = os.environ.get('TV_USER', '')
    
    # Parse CLI arguments
    argv = sys.argv[1:]
    cli_session = None
    cli_signature = None
    
    for i, arg in enumerate(argv):
        if arg == '--session' and i + 1 < len(argv):
            cli_session = argv[i + 1]
        elif arg == '--signature' and i + 1 < len(argv):
            cli_signature = argv[i + 1]
    
    # CLI arguments take precedence
    session = cli_session or session
    signature = cli_signature or signature
    
    return {
        'session': session,
        'signature': signature,
        'tv_user': tv_user,
    }


def require_auth(session: str, signature: str, example_name: str):
    """Check if authentication is required and available."""
    if not session or not signature:
        print(f'Error: {example_name} requires SESSION and SIGNATURE cookies.')
        print('Provide them via .env file or CLI arguments:')
        print('  python examples.py {} --session <SESSION> --signature <SIGNATURE>'.format(example_name))
        sys.exit(1)


# ============================================================================
# EXAMPLE 1: SimpleChart
# ============================================================================

async def simple_chart_example():
    """
    SimpleChart Example - Creates a basic chart with price updates.

    Mirrors tvjs/examples/SimpleChart.js
    """
    print("=" * 60)
    print("EXAMPLE: SimpleChart")
    print("=" * 60)

    # Create client (no auth needed for basic chart)
    client = Client()

    # Set up error handler
    client.on_error(lambda *err: print(f"Client error: {err}"))

    # Connect to WebSocket
    await client.connect()

    # Create chart session using JS-like API: client.Session.Chart()
    chart = client.Session.Chart()

    # Set up error handler
    def on_error(err):
        print(f"Chart error: {err}")

    chart.on_error(on_error)

    # Set up symbol loaded handler
    def on_symbol_loaded():
        print(f'Market "{chart.infos.get("description", "Unknown")}" loaded!')
        print(f'  Symbol: {chart.infos.get("name", "N/A")}')
        print(f'  Exchange: {chart.infos.get("exchange", "N/A")}')
        print(f'  Currency: {chart.infos.get("currency_code", "N/A")}')

    chart.on_symbol_loaded(on_symbol_loaded)

    # Set up update handler
    update_count = [0]  # Use list to allow modification in closure

    def on_update(changes):
        update_count[0] += 1
        if not chart.periods:
            return
        latest = chart.periods[0]
        description = chart.infos.get('description', 'Unknown')
        currency = chart.infos.get('currency_code', '')
        print(f'  [{description}] Update #{update_count[0]}: C={latest.get("close", "N/A")} {currency}')

    chart.on_update(on_update)

    # Set market to BTC/EUR (matches JS: chart.setMarket('BINANCE:BTCEUR', { timeframe: 'D' }))
    print('Setting market to BINANCE:BTCEUR...')
    chart.set_market('BINANCE:BTCEUR', timeframe='D')

    # Wait for data to arrive
    await asyncio.sleep(5)

    # Wait 5 seconds and switch to ETH (matches JS)
    print('\nSetting market to BINANCE:ETHEUR...')
    chart.set_market('BINANCE:ETHEUR', timeframe='D')

    # Wait for data
    await asyncio.sleep(5)

    # Wait 5 seconds and change timeframe (matches JS: chart.setSeries('15'))
    print('\nSetting timeframe to 15 minutes...')
    chart.set_series('15')

    # Wait for data
    await asyncio.sleep(5)

    # Wait 5 seconds and change chart type (matches JS)
    print('\nSetting chart type to Heikin Ashi...')
    chart.set_market('BINANCE:ETHEUR', timeframe='D', type='HeikinAshi')

    # Wait for data
    await asyncio.sleep(5)

    # Cleanup (matches JS: chart.delete() and client.end())
    print('\nClosing the chart...')
    chart.delete()

    print('\nClosing the client...')
    await client.end()

    print("SimpleChart example completed.\n")


# ============================================================================
# EXAMPLE 2: BuiltInIndicator
# ============================================================================

async def builtin_indicator_example():
    """
    BuiltInIndicator Example - Uses a built-in volume profile indicator.
    
    Mirrors tvjs/examples/BuiltInIndicator.js
    
    Note: Free tier users are limited to 1-2 studies per chart.
    If you get "maximum number of studies reached" error, wait a few
    minutes before running again to let the server clean up.
    """
    print("=" * 60)
    print("EXAMPLE: BuiltInIndicator (Volume Profile)")
    print("=" * 60)
    
    config = load_config()
    
    # Create the volume profile indicator (matches JS)
    volume_profile = BuiltInIndicator('VbPFixed@tv-basicstudies-241!')
    
    # Check if auth is needed (matches JS logic)
    need_auth = volume_profile.type not in [
        'VbPFixed@tv-basicstudies-241',
        'VbPFixed@tv-basicstudies-241!',
        'Volume@tv-basicstudies-241',
    ]
    
    if need_auth:
        require_auth(config['session'], config['signature'], 'builtin_indicator')
    
    # Create client with auth if needed (matches JS)
    client = Client(
        token=config['session'] if need_auth else None,
        signature=config['signature'] if need_auth else None,
    )
    
    # Track study error
    study_error = None
    
    def on_client_error(err):
        nonlocal study_error
        err_msg = str(err)
        if 'maximum number of studies' in err_msg.lower():
            study_error = "Free tier limit reached. Please wait a few minutes and try again."
        else:
            study_error = f"Client error: {err_msg}"
    
    client.on_error(on_client_error)
    
    await client.connect()
    
    # Create chart using JS-like API: new client.Session.Chart()
    chart = client.Session.Chart()
    
    def on_chart_error(err):
        nonlocal study_error
        err_msg = str(err)
        if 'maximum number of studies' in err_msg.lower():
            study_error = "Free tier limit reached. Please wait a few minutes and try again."
        print(f"Chart error: {err_msg}")
    
    chart.on_error(on_chart_error)
    chart.set_market('BINANCE:BTCEUR', timeframe='60', range=1)
    
    # Set indicator options (matches JS: volumeProfile.setOption('first_bar_time', Date.now() - 10 ** 8))
    volume_profile.set_option('first_bar_time', int(datetime.now().timestamp() * 1000) - 10**8)
    
    # Create study using JS-like API: new chart.Study(volumeProfile)
    vol_study = chart.Study(volume_profile)
    
    data_processed = False
    
    def on_study_error(err):
        nonlocal study_error, data_processed
        err_msg = str(err)
        if 'maximum number of studies' in err_msg.lower():
            study_error = "Free tier limit reached. Please wait a few minutes and try again."
            print(f"  ERROR: {study_error}")
            data_processed = True  # Signal to exit
        else:
            print(f"  Study error: {err_msg}")
    
    vol_study.on_error(on_study_error)
    
    # Set up update handler (matches JS)
    def on_update(changes):
        nonlocal data_processed
        if data_processed:
            return
        
        print("Volume Profile Data:")
        # Access graphic data if available
        graphic = vol_study.graphic
        if graphic and 'horizHists' in graphic:
            horiz_hists = graphic.get('horizHists', [])
            # Filter for recent bars (lastBarTime === 0) and sort by price
            recent = [h for h in horiz_hists if h.get('lastBarTime') == 0]
            recent.sort(key=lambda x: x.get('priceHigh', 0), reverse=True)
            
            for h in recent[:10]:  # Show top 10
                price_mid = round((h.get('priceHigh', 0) + h.get('priceLow', 0)) / 2)
                rate0 = h.get('rate', [0, 0])[0]
                rate1 = h.get('rate', [0, 0])[1]
                bar = '_' * int(rate0 // 3) + '_' * int(rate1 // 3)
                print(f"  ~ {price_mid} : {bar}")
            
            data_processed = True
            
            # IMPORTANT: Remove study to free up slot for free tier users
            print("  Removing study to free up slot...")
            vol_study.remove()
            
            # Cleanup after first update (matches JS: client.end())
            asyncio.create_task(client.end())
        elif vol_study.periods:
            # Got data but no graphic yet
            print(f"  Got {len(vol_study.periods)} periods, waiting for graphic...")
    
    vol_study.on_update(on_update)
    
    # Wait for completion or timeout
    for i in range(30):
        await asyncio.sleep(1)
        if data_processed:
            break
    
    if study_error:
        print(f"\n  {study_error}")
    
    if not data_processed:
        print("  No data received within timeout. Removing study...")
        vol_study.remove()
        await client.end()
    
    print("\nBuiltInIndicator example completed.\n")


# ============================================================================
# EXAMPLE 3: AllPrivateIndicators
# ============================================================================

async def all_private_indicators_example():
    """
    AllPrivateIndicators Example - Loads all user's private indicators.

    Mirrors tvjs/examples/AllPrivateIndicators.js
    
    Note: Free tier users are limited to 1-2 studies per chart.
    This example processes indicators sequentially, removing each before
    adding the next to stay within free tier limits.
    
    If you get "maximum number of studies reached" error, wait a few
    minutes before running again to let the server clean up.
    """
    print("=" * 60)
    print("EXAMPLE: AllPrivateIndicators")
    print("=" * 60)

    config = load_config()
    require_auth(config['session'], config['signature'], 'all_private_indicators')

    # Create authenticated client (matches JS)
    client = Client(
        token=config['session'],
        signature=config['signature'],
    )
    
    # Track study limit errors
    study_limit_reached = False
    
    def on_client_error(err):
        nonlocal study_limit_reached
        err_msg = str(err)
        if 'maximum number of studies' in err_msg.lower():
            study_limit_reached = True
            print("  ERROR: Free tier study limit reached. Waiting a moment...")
    
    client.on_error(on_client_error)

    await client.connect()

    # Create chart using JS-like API
    chart = client.Session.Chart()
    chart.set_market('BINANCE:BTCEUR', timeframe='D')
    
    def on_chart_error(err):
        nonlocal study_limit_reached
        err_msg = str(err)
        if 'maximum number of studies' in err_msg.lower():
            study_limit_reached = True
    
    chart.on_error(on_chart_error)

    # Fetch private indicators using get_private_indicators (matches JS: TradingView.getPrivateIndicators)
    print("Fetching private indicators...")
    
    try:
        indic_list = await get_private_indicators(config['session'], config['signature'])

        if not indic_list:
            print("No private indicators found for this account.")
            await client.end()
            return

        print(f"Found {len(indic_list)} private indicator(s):")
        print("Note: Processing sequentially to respect free tier study limits.")
        print("Each indicator is removed after data is received.\n")

        # Process each indicator sequentially (matches JS)
        # Free tier: only 1-2 studies at a time, so we remove each after use
        processed_count = 0
        
        for indic in indic_list:
            if study_limit_reached:
                print(f"Skipping remaining indicators due to study limit.")
                print("Please wait a few minutes and run again.")
                break
            
            private_indic = await indic['get']()
            print(f"[{processed_count + 1}/{len(indic_list)}] Loading: {indic['name']}")

            # Create study using JS-like API: new chart.Study(privateIndic)
            indicator = chart.Study(private_indic)
            
            # Track if we've received data
            data_received = False

            def make_ready_callback(name):
                def on_ready():
                    print(f"  Indicator '{name}' loaded!")
                return on_ready

            def make_update_callback(name, ind, marker):
                def on_update(changes):
                    nonlocal data_received, study_limit_reached, processed_count
                    if marker[0] or study_limit_reached:  # Already processed
                        return
                    
                    if ind.periods:
                        print(f"  Plot values: {ind.periods[:3]}")  # Show first 3
                        if ind.strategy_report.get('trades'):
                            print(f"  Strategy trades: {len(ind.strategy_report['trades'])}")
                        
                        marker[0] = True
                        data_received = True
                        processed_count += 1
                        
                        # IMPORTANT: Remove study to free up slot for free tier users
                        print(f"  ✓ Removing '{name}' to free up slot...")
                        ind.remove()
                
                return on_update
            
            def make_error_callback(name, ind, marker):
                def on_error(err):
                    nonlocal study_limit_reached
                    err_msg = str(err)
                    if 'maximum number of studies' in err_msg.lower():
                        study_limit_reached = True
                        marker[0] = True  # Signal to stop waiting
                        print(f"  ✗ Cannot load '{name}': study limit reached")
                    else:
                        print(f"  Study error for '{name}': {err_msg[:100]}")
                return on_error

            # Use list to allow modification in closure
            processed_marker = [False]
            
            indicator.on_ready(make_ready_callback(indic['name']))
            indicator.on_update(make_update_callback(indic['name'], indicator, processed_marker))
            indicator.on_error(make_error_callback(indic['name'], indicator, processed_marker))

            # Wait for data (max 10 seconds per indicator)
            for _ in range(10):
                await asyncio.sleep(1)
                if processed_marker[0]:
                    break
            
            if not processed_marker[0]:
                print(f"  No data for '{indic['name']}', removing...")
                indicator.remove()
            
            print()  # Empty line between indicators

        print(f"Processed {processed_count}/{len(indic_list)} indicators successfully.")
        
        if study_limit_reached:
            print("\nNote: Free tier users are limited to 1-2 studies per chart.")
            print("If you hit the limit frequently, wait a few minutes between runs.")

    except Exception as e:
        print(f"Error fetching private indicators: {e}")
        import traceback
        traceback.print_exc()

    await client.end()

    print("\nAllPrivateIndicators example completed.\n")


# ============================================================================
# EXAMPLE 4: FetchHistoricalData
# ============================================================================

async def fetch_historical_data_example(count: int = 1000):
    """
    FetchHistoricalData Example - Fetches historical OHLCV data and saves to CSV.
    
    Mirrors tvjs/examples/FetchHistoricalData.js
    """
    print("=" * 60)
    print("EXAMPLE: FetchHistoricalData")
    print("=" * 60)
    
    config = load_config()
    require_auth(config['session'], config['signature'], 'fetch_historical_data')
    
    # Number of points to fetch (matches JS: CLI flag --count or env var COUNT)
    COUNT = count
    
    # Create authenticated client (matches JS)
    client = Client(
        token=config['session'],
        signature=config['signature'],
    )
    
    await client.connect()
    
    async def save_to_csv(data: Dict) -> str:
        """Save fetched data to CSV file (matches JS implementation)."""
        periods = data.get('periods', [])
        infos = data.get('infos', {})
        timeframe = data.get('timeframe', 'unknown')
        
        symbol = (infos and (infos.get('pro_name') or infos.get('full_name') or infos.get('series_id'))) or 'market'
        sanitized = str(symbol).replace(':', '_').replace('/', '_').replace('\\', '_')
        filepath = f"{sanitized}_{timeframe}.csv"
        
        # Sort ascending by time (oldest first) - matches JS
        sorted_periods = sorted(periods, key=lambda x: x.get('time', 0))
        
        with open(filepath, 'w', newline='') as f:
            # Header (matches JS)
            f.write('timestamp,datetime,open,high,low,close,volume,vwap,trade_count,tick_volume,close_adj,percent_change\n')
            
            for p in sorted_periods:
                ts = p.get('time', 0)
                time_ms = ts * 1000 if ts < 1e12 else ts
                datetime_str = datetime.fromtimestamp(time_ms / 1000).isoformat()
                
                open_price = p.get('open', '')
                high = p.get('max', '')
                low = p.get('min', '')
                close = p.get('close', '')
                volume = p.get('volume', '')
                
                # Calculate percent change (matches JS)
                pct_change = ''
                if open_price != '' and open_price != 0 and close != '':
                    try:
                        pct_change = f"{((close - open_price) / open_price) * 100:.6f}"
                    except:
                        pass
                
                row = [ts, datetime_str, open_price, high, low, close, volume, '', '', '', '', pct_change]
                f.write(','.join(str(c) for c in row) + '\n')
        
        return filepath
    
    async def fetch_for_timeframe(timeframe: str, count: int, timeout_ms: int = 20000):
        """Fetch data for a specific timeframe (matches JS)."""
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        
        # Create chart using JS-like API: new client.Session.Chart()
        chart = client.Session.Chart()
        
        def on_update(changes):
            periods = chart.periods
            if len(periods) >= min(count, 1) and not future.done():
                # Resolve with a shallow copy to avoid internal mutation issues
                future.set_result({
                    'timeframe': timeframe,
                    'periods': periods[:count],
                    'infos': chart.infos
                })
                cleanup()
        
        def on_error(err):
            if not future.done():
                future.set_exception(Exception(str(err)))
            cleanup()
        
        def cleanup():
            # No-op to avoid memory leak (matches JS)
            pass
        
        # Safety timeout (matches JS)
        timer = loop.call_later(timeout_ms / 1000, lambda: (
            future.set_exception(asyncio.TimeoutError(f"Timeout fetching {timeframe}")) or cleanup()
        ) if not future.done() else None)
        
        # Attach listeners (matches JS)
        chart.on_error(lambda e: (timer.cancel(), on_error(e)) if not future.done() else None)
        chart.on_update(lambda c: (timer.cancel(), on_update(c)) if not future.done() else None)
        
        # Request the market with desired range (matches JS)
        try:
            chart.set_market('KUCOIN:XMRUSDT', timeframe=timeframe, range=count)
        except Exception as e:
            timer.cancel()
            on_error(e)
        
        try:
            return await future
        finally:
            chart.delete()
    
    # Timeframes to fetch (matches JS)
    timeframes = ['5', '60', '1D']
    
    try:
        for tf in timeframes:
            print(f"\nFetching {tf} bars...")
            try:
                data = await fetch_for_timeframe(tf, COUNT, 30000)
                print(f"Got {len(data['periods'])} bars for {data['timeframe']} (requested {COUNT})")
                
                # Print most recent 3 bars (matches JS)
                if data['periods']:
                    print("  Recent bars:")
                    for bar in data['periods'][:3]:
                        print(f"    {bar.get('time')}: O={bar.get('open')} H={bar.get('max')} L={bar.get('min')} C={bar.get('close')}")
                
                # Save to CSV (matches JS)
                try:
                    csv_path = await save_to_csv(data)
                    print(f"  Saved CSV for {tf}: {csv_path}")
                except Exception as e:
                    print(f"  Failed to save CSV: {e}")
                    
            except asyncio.TimeoutError as e:
                print(f"  Failed to fetch {tf}: {e}")
            except Exception as e:
                print(f"  Failed to fetch {tf}: {e}")
    
    finally:
        # Matches JS: client.end()
        await client.end()
    
    print("\nFetchHistoricalData example completed.\n")


# ============================================================================
# EXAMPLE 5: ListSavedPineScripts
# ============================================================================

async def list_saved_scripts_example(json_output: bool = False, details: bool = False):
    """
    ListSavedPineScripts Example - Lists saved/private Pine scripts.
    
    Mirrors tvjs/examples/ListSavedPineScripts.js
    """
    print("=" * 60)
    print("EXAMPLE: ListSavedPineScripts")
    print("=" * 60)
    
    config = load_config()
    require_auth(config['session'], config['signature'], 'list_saved_scripts')
    
    try:
        # Use get_private_indicators (matches JS: TradingView.getPrivateIndicators)
        print("Fetching saved scripts...")
        scripts = await get_private_indicators(config['session'], config['signature'])
        
        if not scripts:
            print("No saved scripts found for this account.")
            return
        
        if json_output:
            if not details:
                # Simple JSON output (matches JS)
                output = [
                    {
                        'id': s['id'],
                        'name': s['name'],
                        'access': s['access'],
                        'kind': s.get('type', 'study'),
                    }
                    for s in scripts
                ]
                print(json.dumps(output, indent=2))
            else:
                # Detailed JSON output with metadata (matches JS)
                output = []
                for s in scripts:
                    entry = {
                        'id': s['id'],
                        'name': s['name'],
                        'access': s['access'],
                        'kind': s.get('type', 'study'),
                    }
                    
                    try:
                        # Fetch full metadata
                        ind = await s['get']()
                        
                        entry['pineId'] = ind.pine_id
                        entry['pineVersion'] = ind.pine_version
                        
                        # Extract inputs
                        inputs = []
                        for inp_id, inp_data in ind.inputs.items():
                            inputs.append({
                                'id': inp_id,
                                'name': inp_data.get('name', ''),
                                'inline': inp_data.get('inline', ''),
                                'internalID': inp_data.get('internalID', ''),
                                'tooltip': inp_data.get('tooltip', ''),
                                'type': inp_data.get('type', ''),
                                'default': inp_data.get('value'),
                                'isHidden': inp_data.get('isHidden', False),
                                'isFake': inp_data.get('isFake', False),
                                'options': inp_data.get('options'),
                            })
                        entry['inputs'] = inputs
                    except Exception as e:
                        entry['error'] = str(e)
                    
                    output.append(entry)
                
                print(json.dumps(output, indent=2))
        else:
            # Text output
            print(f"\nFound {len(scripts)} saved scripts:\n")
            
            for idx, s in enumerate(scripts):
                if details:
                    try:
                        ind = await s['get']()
                        inputs_count = len(ind.inputs)
                        print(f"  #{idx + 1}: {s['id']} - {s['name']} (version={ind.pine_version}, inputs={inputs_count})")
                    except Exception as e:
                        print(f"  #{idx + 1}: {s['id']} - {s['name']} (error: {e})")
                else:
                    print(f"  #{idx + 1}: {s['id']} - {s['name']}")
    
    except Exception as e:
        print(f"Error listing saved scripts: {e}")
    
    print("\nListSavedPineScripts example completed.\n")


# ============================================================================
# EXAMPLE 6: Search
# ============================================================================

async def search_example():
    """
    Search Example - Search for markets and indicators.
    
    Mirrors tvjs/examples/Search.js
    """
    print("=" * 60)
    print("EXAMPLE: Search")
    print("=" * 60)
    
    # Search for markets (matches JS: TradingView.searchMarketV3('BINANCE:'))
    print("\nSearching for BINANCE markets...")
    markets = await search_market_v3('BINANCE:')
    print(f"Found {len(markets)} markets:")
    for m in markets[:5]:  # Show first 5
        print(f"  - {m['id']}: {m['description']}")
    
    # Search for indicators (matches JS: TradingView.searchIndicator('RSI'))
    print("\nSearching for RSI indicators...")
    indicators = await search_indicator('RSI')
    print(f"Found {len(indicators)} indicators:")
    for i in indicators[:5]:  # Show first 5
        print(f"  - {i['name']} ({i['id']}) - {i['access']}")
    
    print("\nSearch example completed.\n")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

async def run_all_examples():
    """Run all examples sequentially."""
    print("\n" + "=" * 60)
    print("RUNNING ALL EXAMPLES")
    print("=" * 60 + "\n")
    
    try:
        # SimpleChart (no auth required)
        await simple_chart_example()
        
        # Search (no auth required)
        await search_example()
        
        # Check if we have auth for remaining examples
        config = load_config()
        if config['session'] and config['signature']:
            # BuiltInIndicator
            await builtin_indicator_example()
            
            # AllPrivateIndicators
            await all_private_indicators_example()
            
            # FetchHistoricalData
            await fetch_historical_data_example(count=100)
            
            # ListSavedPineScripts
            await list_saved_scripts_example(json_output=False, details=True)
        else:
            print("Skipping authenticated examples (no SESSION/SIGNATURE provided)\n")
            
    except Exception as e:
        print(f"Error running examples: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main entry point."""
    argv = sys.argv[1:]
    
    if not argv:
        print(__doc__)
        print("\nAvailable examples:")
        print("  simple_chart              - Basic chart with price updates")
        print("  builtin_indicator         - Volume profile indicator")
        print("  all_private_indicators    - Load all private indicators")
        print("  fetch_historical_data     - Fetch historical data to CSV")
        print("  list_saved_scripts        - List saved Pine scripts")
        print("  search                    - Search markets and indicators")
        print("  all                       - Run all examples")
        print("\nOptions:")
        print("  --session SESSION         - Override SESSION cookie")
        print("  --signature SIGNATURE     - Override SIGNATURE cookie")
        print("  --count N                 - Number of bars to fetch (for fetch_historical_data)")
        print("  --json                    - JSON output (for list_saved_scripts)")
        print("  --details                 - Show detailed info (for list_saved_scripts)")
        sys.exit(0)
    
    example_name = argv[0]
    
    # Check for --count flag
    count = 1000
    if '--count' in argv:
        try:
            count_idx = argv.index('--count')
            count = int(argv[count_idx + 1])
        except:
            pass
    
    # Check for --json flag
    json_output = '--json' in argv
    
    # Check for --details flag
    details = '--details' in argv
    
    async def run():
        if example_name == 'simple_chart':
            await simple_chart_example()
        elif example_name == 'builtin_indicator':
            await builtin_indicator_example()
        elif example_name == 'all_private_indicators':
            await all_private_indicators_example()
        elif example_name == 'fetch_historical_data':
            await fetch_historical_data_example(count=count)
        elif example_name == 'list_saved_scripts':
            await list_saved_scripts_example(json_output=json_output, details=details)
        elif example_name == 'search':
            await search_example()
        elif example_name == 'all':
            await run_all_examples()
        else:
            print(f"Unknown example: {example_name}")
            print("Use 'python examples.py' to see available examples.")
            sys.exit(1)
    
    asyncio.run(run())


if __name__ == '__main__':
    main()
