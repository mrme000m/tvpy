#!/usr/bin/env python3
"""
Comprehensive TradingView Indicator Examples
============================================

This file demonstrates all major built-in indicator categories with:
- Different assets (Crypto, Forex, Stocks, Commodities)
- Multiple timeframes (1m, 5m, 15m, 1h, 4h, 1D)
- Various sample sizes (50, 100, 200, 500 bars)
- Custom input configurations
- Results saved to JSON and CSV files

IMPORTANT - Free Tier Usage:
============================
TradingView's free tier allows only 1-2 studies per chart. This example
processes indicators SEQUENTIALLY - creating one study, waiting for data,
removing it, then moving to the next. This respects free tier limits.

If you get "maximum number of studies reached" error:
1. Wait 3-5 minutes for server cleanup
2. Run the test again
3. Consider using fewer indicators or smaller sample sizes

Usage:
    python indicator_examples.py [category] [--symbol SYMBOL] [--timeframe TF] [--output DIR]

Categories:
    all           - Run all indicator tests (takes longer)
    moving_averages - MA, EMA, SMA, VWAP, etc.
    oscillators   - RSI, MACD, Stochastic, etc.
    volume        - Volume Profile, OBV, VWMA, etc.
    trend         - ADX, Supertrend, Ichimoku, etc.
    volatility    - Bollinger Bands, ATR, Keltner, etc.
    candlestick   - Pattern recognition indicators
    custom        - Private indicators with custom inputs

Examples:
    python indicator_examples.py moving_averages --symbol BINANCE:BTCUSDT --timeframe 60
    python indicator_examples.py oscillators --symbol BINANCE:ETHUSDT --timeframe 240 --sample_size 500
    python indicator_examples.py all --output ./indicator_results
"""

import asyncio
import json
import csv
import os
import sys
import argparse
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional
from pathlib import Path

from tradingview import Client, PineIndicator, get_indicator


def load_credentials():
    """Load credentials from environment variables"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip()
    
    return os.environ.get('SESSION'), os.environ.get('SIGNATURE')


@dataclass
class IndicatorResult:
    """Container for indicator test results"""
    indicator_name: str
    indicator_id: str
    symbol: str
    timeframe: str
    sample_size: int
    timestamp: str
    periods_count: int
    plots: Dict[str, Any]
    inputs_used: Dict[str, Any]
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class IndicatorTester:
    """
    Comprehensive indicator testing framework.
    
    PROCESSES INDICATORS SEQUENTIALLY to respect free tier limits:
    1. Create ONE chart
    2. Add ONE study
    3. Wait for data
    4. Remove study immediately
    5. Wait 1-2 seconds
    6. Add next study
    """
    
    # Major built-in indicators by category (verified IDs from builtins.json)
    BUILTIN_INDICATORS = {
        'moving_averages': [
            ('Simple Moving Average', 'STD;SMA'),
            ('Exponential Moving Average', 'STD;EMA'),
            ('Weighted Moving Average', 'STD;WMA'),
            ('Hull Moving Average', 'STD;Hull%1MA'),
            ('Volume Weighted Moving Average', 'STD;VWMA'),
            ('VWAP', 'STD;VWAP'),
            ('Arnaud Legoux Moving Average', 'STD;Arnaud%1Legoux%1Moving%1Average'),
            ('Kaufman Adaptive Moving Average', 'STD;Kaufmans_Adaptive_Moving_Average'),
            ('Moving Average Ribbon', 'STD;MA%Ribbon'),
            ('Double EMA', 'STD;DEMA'),
            ('Triple EMA', 'STD;TEMA'),
            ('Zero Lag EMA', 'STD;Zero%1Lag%1Exponential%1Moving%1Average'),
        ],
        'oscillators': [
            ('Relative Strength Index', 'STD;RSI'),
            ('MACD', 'STD;MACD'),
            ('Stochastic', 'STD;Stochastic'),
            ('Stochastic RSI', 'STD;Stochastic_RSI'),
            ('Stochastic Momentum Index', 'STD;SMI'),
            ('Commodity Channel Index', 'STD;CCI'),
            ('Money Flow Index', 'STD;Money_Flow'),
            ('Williams %R', 'STD;Willams_R'),
            ('Awesome Oscillator', 'STD;Awesome_Oscillator'),
            ('Relative Vigor Index', 'STD;Relative_Vigor_Index'),
            ('Chande Momentum Oscillator', 'STD;Chande_Momentum_Oscillator'),
            ('Connors RSI', 'STD;Connors_RSI'),
        ],
        'volume': [
            ('Volume', 'STD;Volume'),
            ('On Balance Volume', 'STD;On_Balance_Volume'),
            ('Volume Weighted Moving Average', 'STD;VWMA'),
            ('Accumulation/Distribution', 'STD;Accumulation_Distribution'),
            ('Chaikin Money Flow', 'STD;Chaikin_Money_Flow'),
            ('Ease of Movement', 'STD;EOM'),
            ('Force Index', 'STD;EFI'),
            ('Negative Volume Index', 'STD;Negative_Volume_Index'),
            ('Positive Volume Index', 'STD;Positive_Volume_Index'),
            ('Price Volume Trend', 'STD;Price_Volume_Trend'),
            ('Relative Volume at Time', 'STD;Relative_Volume_at_Time'),
            ('Cumulative Volume Delta', 'STD;Cumulative_Volume_Delta'),
        ],
        'trend': [
            ('Average Directional Index', 'STD;ADX'),
            ('DMI', 'STD;DMI'),
            ('Ichimoku Cloud', 'STD;Ichimoku%1Cloud'),
            ('Parabolic SAR', 'STD;PSAR'),
            ('Supertrend', 'STD;Supertrend'),
            ('Trend Strength Index', 'STD;Trend_Strength_Index'),
            ('BBTrend', 'STD;BBTrend'),
            ('Aroon', 'STD;Aroon'),
            ('Detrended Price Oscillator', 'STD;DPO'),
            ('Vortex Indicator', 'STD;Vortex%1Indicator'),
        ],
        'volatility': [
            ('Bollinger Bands', 'STD;Bollinger_Bands'),
            ('Bollinger Bands %b', 'STD;Bollinger_Bands_B'),
            ('Bollinger Bands Width', 'STD;Bollinger_Bands_Width'),
            ('Average True Range', 'STD;Average_True_Range'),
            ('Keltner Channels', 'STD;Keltner_Channels'),
            ('Donchian Channels', 'STD;Donchian_Channels'),
            ('Historical Volatility', 'STD;Historical_Volatility'),
            ('Chaikin Volatility', 'STD;Chaikin_Volatility'),
            ('Volatility Stop', 'STD;Volatility_Stop'),
        ],
        'candlestick': [
            ('Doji', 'STD;Candlestick_Pattern_Doji'),
            ('Engulfing - Bullish', 'STD;Candlestick_Pattern_Bullish_Engulfing'),
            ('Engulfing - Bearish', 'STD;Candlestick_Pattern_Bearish_Engulfing'),
            ('Hammer - Bullish', 'STD;Candlestick_Pattern_Bullish_Hammer'),
            ('Shooting Star - Bearish', 'STD;Candlestick_Pattern_Bearish_Shooting_Star'),
            ('Morning Star - Bullish', 'STD;Candlestick_Pattern_Bullish_Morning_Star'),
            ('Evening Star - Bearish', 'STD;Candlestick_Pattern_Bearish_Evening_Star'),
            ('Harami - Bullish', 'STD;Candlestick_Pattern_Bullish_Harami'),
            ('Harami - Bearish', 'STD;Candlestick_Pattern_Bearish_Harami'),
        ],
    }
    
    ASSETS = {
        'crypto': [
            'BINANCE:BTCUSDT',
            'BINANCE:ETHUSDT',
            'BINANCE:SOLUSDT',
            'BINANCE:XRPUSDT',
        ],
        'forex': [
            'OANDA:EURUSD',
            'OANDA:GBPUSD',
            'OANDA:USDJPY',
            'OANDA:XAUUSD',
        ],
    }
    
    TIMEFRAMES = ['15', '60', '240', '1D']
    SAMPLE_SIZES = [100, 200, 500]
    
    def __init__(self, output_dir: str = './indicator_results'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[IndicatorResult] = []
        self.session = None
        self.signature = None
        self.study_limit_reached = False
        
    async def initialize(self):
        """Load credentials"""
        self.session, self.signature = load_credentials()
        
    def save_results(self, filename: str):
        """Save results to JSON and CSV"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        json_path = self.output_dir / f"{filename}_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump([r.to_dict() for r in self.results], f, indent=2, default=str)
        
        csv_path = self.output_dir / f"{filename}_{timestamp}.csv"
        if self.results:
            with open(csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.results[0].to_dict().keys())
                writer.writeheader()
                for result in self.results:
                    writer.writerow(result.to_dict())
        
        print(f"  Results saved to:")
        print(f"    JSON: {json_path}")
        print(f"    CSV: {csv_path}")

    async def test_indicator_sequential(
        self,
        client: Client,
        chart,
        name: str,
        ind_id: str,
        symbol: str,
        timeframe: str,
        sample_size: int
    ) -> IndicatorResult:
        """
        Test a single indicator using sequential pattern (free tier friendly).
        
        Pattern:
        1. Fetch indicator
        2. Create study
        3. Wait for data/error
        4. Remove study immediately
        5. Return result
        """
        result = IndicatorResult(
            indicator_name=name,
            indicator_id=ind_id,
            symbol=symbol,
            timeframe=timeframe,
            sample_size=sample_size,
            timestamp=datetime.now().isoformat(),
            periods_count=0,
            plots={},
            inputs_used={},
            error=None
        )
        
        if self.study_limit_reached:
            result.error = "Skipped due to study limit"
            return result
        
        try:
            # Fetch indicator from pine-facade API
            indicator = await get_indicator(ind_id, session=self.session, signature=self.signature)
            
            # Create study
            study = chart.Study(indicator)
            
            # Track completion
            processed = [False]  # Use list for mutable closure
            study_error = None
            
            def on_update(changes):
                if study.periods and not processed[0]:
                    result.periods_count = len(study.periods)
                    if study.periods:
                        last_period = study.periods[0]  # Most recent
                        result.plots = {
                            k: v for k, v in last_period.items()
                            if k not in ['$time', 'time']
                        }
                    processed[0] = True
            
            def on_error(err):
                nonlocal study_error
                study_error = str(err)
                if 'maximum number of studies' in study_error.lower():
                    self.study_limit_reached = True
                processed[0] = True
            
            study.on_update(on_update)
            study.on_error(on_error)
            
            # Wait for data (max 15 seconds)
            for _ in range(15):
                await asyncio.sleep(1)
                if processed[0]:
                    break
            
            # Capture any error
            if study_error:
                result.error = study_error
            elif not result.periods_count:
                result.error = "Timeout waiting for data"
            
            # ALWAYS remove study to free up slot
            study.remove()
            
        except Exception as e:
            result.error = str(e)
            if 'maximum number of studies' in result.error.lower():
                self.study_limit_reached = True
        
        return result

    async def test_category(
        self,
        category: str,
        symbols: List[str] = None,
        timeframes: List[str] = None,
        sample_sizes: List[int] = None
    ):
        """
        Test all indicators in a category SEQUENTIALLY.
        
        Free tier pattern: One chart, one study at a time, remove after each.
        """
        if category not in self.BUILTIN_INDICATORS:
            print(f"Unknown category: {category}")
            return
            
        symbols = symbols or self.ASSETS['crypto'][:1]  # Default to 1 symbol
        timeframes = timeframes or ['60']
        sample_sizes = sample_sizes or [100]
        
        indicators = self.BUILTIN_INDICATORS[category]
        
        print(f"\n{'='*60}")
        print(f"Testing {category.upper()} Indicators")
        print(f"{'='*60}")
        print(f"Indicators: {len(indicators)}")
        print(f"Assets: {symbols}")
        print(f"Timeframes: {timeframes}")
        print(f"Sample sizes: {sample_sizes}")
        total = len(indicators) * len(symbols) * len(timeframes) * len(sample_sizes)
        print(f"Total tests: {total}")
        print(f"\nNote: Processing SEQUENTIALLY to respect free tier limits.")
        print(f"Each indicator is removed immediately after data collection.\n")
        
        # Create ONE client and ONE chart for all tests
        client = Client(session=self.session, signature=self.signature)
        
        def on_client_error(err):
            err_msg = str(err)
            if 'maximum number of studies' in err_msg.lower():
                self.study_limit_reached = True
                print("  WARNING: Study limit reached!")
        
        client.on_error(on_client_error)
        await client.connect()
        
        # Create chart
        chart = client.Session.Chart()
        
        def on_chart_error(err):
            err_msg = str(err)
            if 'maximum number of studies' in err_msg.lower():
                self.study_limit_reached = True
        
        chart.on_error(on_chart_error)
        
        # Set market with first symbol/timeframe/size
        # We'll change these as needed
        chart.set_market(symbols[0], timeframe=timeframes[0], range=sample_sizes[0])
        
        # Wait for chart to be ready
        chart_ready = asyncio.Future()
        def on_chart_ready(changes):
            if chart.periods and not chart_ready.done():
                chart_ready.set_result(True)
        chart.on_update(on_chart_ready)
        
        try:
            await asyncio.wait_for(chart_ready, timeout=15)
            print(f"Chart ready with {len(chart.periods)} periods\n")
        except asyncio.TimeoutError:
            print("Warning: Chart data timeout, continuing anyway...")
        
        # Process indicators sequentially
        completed = 0
        total_tests = len(indicators) * len(symbols) * len(timeframes) * len(sample_sizes)
        
        for name, ind_id in indicators:
            if self.study_limit_reached:
                print(f"  Skipping remaining indicators (study limit reached)")
                break
                
            for symbol in symbols:
                for tf in timeframes:
                    for size in sample_sizes:
                        completed += 1
                        print(f"  [{completed}/{total_tests}] {name} on {symbol} ({tf}, {size} bars)...", end=' ', flush=True)
                        
                        # Update chart if needed
                        if symbol != symbols[0] or tf != timeframes[0] or size != sample_sizes[0]:
                            chart.set_market(symbol, timeframe=tf, range=size)
                            await asyncio.sleep(0.5)  # Brief pause for chart update
                        
                        # Test indicator (sequential pattern)
                        result = await self.test_indicator_sequential(
                            client, chart, name, ind_id, symbol, tf, size
                        )
                        self.results.append(result)
                        
                        if result.error:
                            print(f"ERROR: {result.error[:60]}")
                        else:
                            print(f"OK ({result.periods_count} periods)")
                        
                        # Brief pause before next study (helps with free tier)
                        await asyncio.sleep(0.5)
        
        # Cleanup
        chart.delete()
        await client.end()
        
        # Save results
        self.save_results(f"{category}_results")
        
        # Print summary
        success = sum(1 for r in self.results if not r.error)
        print(f"\n{category.upper()} Summary:")
        print(f"  Total: {len(self.results)}")
        print(f"  Success: {success}")
        print(f"  Failed: {len(self.results) - success}")
        
        if self.study_limit_reached:
            print(f"\n  NOTE: Study limit was reached. Wait 3-5 minutes and try again.")
            print(f"  Successfully processed indicators will be cached in results.")


async def run_comprehensive_tests(args):
    """Run comprehensive indicator tests"""
    
    tester = IndicatorTester(output_dir=args.output)
    await tester.initialize()
    
    if args.category == 'all':
        categories = list(tester.BUILTIN_INDICATORS.keys())
    elif args.category == 'custom':
        print("Custom indicator examples not yet implemented in batch mode.")
        print("Use test_single_indicator.py for testing private indicators.")
        return
    else:
        categories = [args.category]
    
    # Determine test parameters
    symbols = [args.symbol] if args.symbol else tester.ASSETS['crypto'][:1]
    timeframes = [args.timeframe] if args.timeframe else ['60']
    sample_sizes = [int(args.sample_size)] if args.sample_size else [100]
    
    for category in categories:
        await tester.test_category(category, symbols, timeframes, sample_sizes)
        tester.results = []  # Reset for next category
        tester.study_limit_reached = False


def main():
    parser = argparse.ArgumentParser(
        description='Comprehensive TradingView Indicator Examples',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Test moving averages on BTC with 1h timeframe
    python indicator_examples.py moving_averages --symbol BINANCE:BTCUSDT --timeframe 60
    
    # Test oscillators with custom sample size
    python indicator_examples.py oscillators --symbol BINANCE:ETHUSDT --timeframe 240 --sample_size 500
    
    # Run all categories (takes longer, may hit study limits)
    python indicator_examples.py all --output ./results
    
    # If you get "study limit" errors, wait 3-5 minutes and try again
        """
    )
    
    parser.add_argument(
        'category',
        choices=['all', 'moving_averages', 'oscillators', 'volume', 'trend', 'volatility', 'candlestick', 'custom'],
        help='Indicator category to test'
    )
    parser.add_argument('--symbol', help='Symbol to test (default: BINANCE:BTCUSDT)')
    parser.add_argument('--timeframe', help='Timeframe (default: 60)')
    parser.add_argument('--sample_size', help='Sample size in bars (default: 100)')
    parser.add_argument('--output', default='./indicator_results', help='Output directory for results')
    
    args = parser.parse_args()
    
    asyncio.run(run_comprehensive_tests(args))


if __name__ == '__main__':
    main()
