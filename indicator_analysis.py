#!/usr/bin/env python3
"""
TradingView Indicator Analysis Tool
====================================

Comprehensive analysis of indicators across multiple assets, timeframes,
and configurations with full output saving capabilities.

IMPORTANT - Free Tier Usage:
============================
This tool processes indicators SEQUENTIALLY to respect TradingView's free
tier limits (1-2 studies per chart). Each indicator is created, data is
collected, and the indicator is immediately removed before adding the next.

If you get "maximum number of studies reached" error:
1. Wait 3-5 minutes for server cleanup
2. Reduce the number of indicators being tested
3. Test in smaller batches

Usage:
    python indicator_analysis.py [command] [options]

Commands:
    scan        - Scan and categorize all available indicators
    benchmark   - Run benchmark tests across assets/timeframes
    compare     - Compare multiple indicators side-by-side

Examples:
    # Scan all built-in indicators
    python indicator_analysis.py scan --output ./scan_results
    
    # Benchmark RSI across multiple assets (sequential processing)
    python indicator_analysis.py benchmark --indicator RSI --assets BTC,ETH --timeframes 15,60
    
    # Compare MACD vs RSI
    python indicator_analysis.py compare --indicators MACD,RSI --symbol BINANCE:BTCUSDT
"""

import asyncio
import json
import csv
import os
import sys
import argparse
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from collections import defaultdict
import statistics

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
class AnalysisConfig:
    """Configuration for indicator analysis"""
    symbol: str
    timeframe: str
    sample_size: int
    indicator_name: str
    indicator_id: str
    input_overrides: Dict[str, Any] = field(default_factory=dict)
    category: str = ""


@dataclass
class AnalysisResult:
    """Complete analysis results for an indicator"""
    config: AnalysisConfig
    periods: List[Dict] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'config': asdict(self.config),
            'periods': self.periods,
            'statistics': self.statistics,
            'error': self.error
        }


class IndicatorScanner:
    """Scan and categorize all available indicators"""
    
    def __init__(self, builtins_path: str = './builtins.json'):
        self.builtins_path = Path(builtins_path)
        self.indicators = []
        self.categories = defaultdict(list)
        
    def load_builtins(self):
        """Load built-in indicators from JSON"""
        with open(self.builtins_path) as f:
            self.indicators = json.load(f)
        
        for ind in self.indicators:
            name = ind.get('name', '').lower()
            
            if any(x in name for x in ['candlestick', 'pattern', 'doji', 'engulfing', 'star', 'hammer']):
                self.categories['candlestick'].append(ind)
            elif any(x in name for x in ['volume', 'obv', 'vwma', 'vp', 'profile', 'accumulation', 'chaikin']):
                self.categories['volume'].append(ind)
            elif any(x in name for x in ['rsi', 'macd', 'stochastic', 'cci', 'mfi', 'momentum', 'williams', 'awesome', 'oscillator']):
                self.categories['oscillators'].append(ind)
            elif any(x in name for x in ['bollinger', 'atr', 'keltner', 'donchian', 'volatility']):
                self.categories['volatility'].append(ind)
            elif any(x in name for x in ['sma', 'ema', 'wma', 'vwap', 'moving average', 'hull', 'kaufman', 'arnaud']):
                self.categories['moving_averages'].append(ind)
            elif any(x in name for x in ['adx', 'supertrend', 'ichimoku', 'parabolic', 'dmi', 'trend', 'aroon']):
                self.categories['trend'].append(ind)
            else:
                self.categories['other'].append(ind)
    
    def generate_report(self, output_dir: str = './indicator_scan'):
        """Generate comprehensive scan report"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        report = {
            'scan_timestamp': datetime.now().isoformat(),
            'total_indicators': len(self.indicators),
            'categories': {}
        }
        
        for category, indicators in sorted(self.categories.items()):
            report['categories'][category] = {
                'count': len(indicators),
                'indicators': [
                    {
                        'name': ind.get('name'),
                        'id': ind.get('id'),
                        'version': ind.get('version'),
                        'inputs_count': ind.get('inputsCount'),
                        'plots_count': ind.get('plotsCount'),
                    }
                    for ind in sorted(indicators, key=lambda x: x.get('name', ''))
                ]
            }
        
        json_path = output_dir / f'indicator_scan_{timestamp}.json'
        with open(json_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n{'='*60}")
        print("INDICATOR SCAN RESULTS")
        print(f"{'='*60}")
        print(f"Total Indicators: {len(self.indicators)}")
        print(f"\nBy Category:")
        for category, indicators in sorted(self.categories.items()):
            print(f"  {category:20s}: {len(indicators):4d} indicators")
        print(f"\nReport saved to: {json_path}")
        
        return report


class IndicatorBenchmark:
    """
    Benchmark indicators across assets and timeframes.
    
    Uses SEQUENTIAL processing to respect free tier limits.
    """
    
    def __init__(self, session: str = None, signature: str = None):
        self.session = session
        self.signature = signature
        self.results = []
        self.study_limit_reached = False
        
    async def run_benchmark(
        self,
        indicator_name: str,
        indicator_id: str,
        assets: List[str],
        timeframes: List[str],
        sample_sizes: List[int],
        output_dir: str = './benchmark_results'
    ):
        """Run benchmark across multiple configurations sequentially"""
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"BENCHMARK: {indicator_name}")
        print(f"{'='*60}")
        print(f"Assets: {assets}")
        print(f"Timeframes: {timeframes}")
        print(f"Sample Sizes: {sample_sizes}")
        print(f"\nNote: Processing SEQUENTIALLY to respect free tier limits.\n")
        
        # Create ONE client
        client = Client(session=self.session, signature=self.signature)
        client.on_error(lambda *err: None)
        await client.connect()
        
        # Create ONE chart
        chart = client.Session.Chart()
        chart.set_market(assets[0], timeframe=timeframes[0], range=sample_sizes[0])
        
        # Wait for chart
        chart_ready = asyncio.Future()
        def on_ready(changes):
            if chart.periods and not chart_ready.done():
                chart_ready.set_result(True)
        chart.on_update(on_ready)
        
        try:
            await asyncio.wait_for(chart_ready, timeout=15)
        except asyncio.TimeoutError:
            print("Warning: Chart data timeout")
        
        total_tests = len(assets) * len(timeframes) * len(sample_sizes)
        completed = 0
        
        for asset in assets:
            for tf in timeframes:
                for size in sample_sizes:
                    if self.study_limit_reached:
                        print(f"  Skipping remaining tests (study limit)")
                        break
                        
                    completed += 1
                    print(f"[{completed}/{total_tests}] Testing {asset} @ {tf} ({size} bars)...", end=' ', flush=True)
                    
                    # Update chart if needed
                    if asset != assets[0] or tf != timeframes[0] or size != sample_sizes[0]:
                        chart.set_market(asset, timeframe=tf, range=size)
                        await asyncio.sleep(0.5)
                    
                    result = await self._test_single_config(
                        chart, indicator_name, indicator_id, asset, tf, size
                    )
                    self.results.append(result)
                    
                    if result.error:
                        print(f"ERROR: {result.error[:50]}")
                    else:
                        print(f"OK ({len(result.periods)} periods)")
                    
                    await asyncio.sleep(0.5)  # Pause between tests
        
        chart.delete()
        await client.end()
        
        await self._save_benchmark_results(output_dir, indicator_name)
        
        return self.results
    
    async def _test_single_config(
        self,
        chart,
        name: str,
        ind_id: str,
        symbol: str,
        timeframe: str,
        sample_size: int
    ) -> AnalysisResult:
        """Test single configuration (sequential pattern)"""
        
        config = AnalysisConfig(
            symbol=symbol,
            timeframe=timeframe,
            sample_size=sample_size,
            indicator_name=name,
            indicator_id=ind_id
        )
        
        result = AnalysisResult(config=config)
        
        try:
            indicator = await get_indicator(ind_id, session=self.session, signature=self.signature)
            study = chart.Study(indicator)
            
            processed = [False]
            study_error = None
            
            def on_update(changes):
                if study.periods and not processed[0]:
                    result.periods = [
                        {k: v for k, v in p.items() if not k.startswith('$')}
                        for p in study.periods[:50]  # Store last 50
                    ]
                    self._calculate_statistics(result)
                    processed[0] = True
            
            def on_error(err):
                nonlocal study_error
                study_error = str(err)
                if 'maximum number of studies' in study_error.lower():
                    self.study_limit_reached = True
                processed[0] = True
            
            study.on_update(on_update)
            study.on_error(on_error)
            
            for _ in range(15):
                await asyncio.sleep(1)
                if processed[0]:
                    break
            
            if study_error:
                result.error = study_error
            elif not result.periods:
                result.error = "Timeout"
            
            study.remove()
            
        except Exception as e:
            result.error = str(e)
            if 'maximum number of studies' in result.error.lower():
                self.study_limit_reached = True
        
        return result
    
    def _calculate_statistics(self, result: AnalysisResult):
        """Calculate statistics for indicator values"""
        if not result.periods:
            return
        
        plot_keys = set()
        for p in result.periods:
            plot_keys.update(k for k in p.keys() if k not in ['time', 'timestamp'])
        
        stats = {}
        for key in plot_keys:
            values = [p.get(key) for p in result.periods if key in p]
            values = [v for v in values if v is not None and isinstance(v, (int, float))]
            
            if values:
                stats[key] = {
                    'mean': statistics.mean(values),
                    'stdev': statistics.stdev(values) if len(values) > 1 else 0,
                    'min': min(values),
                    'max': max(values),
                    'last': values[-1],
                }
        
        result.statistics = stats
    
    async def _save_benchmark_results(self, output_dir: Path, indicator_name: str):
        """Save benchmark results"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_name = indicator_name.replace(' ', '_').replace('%', 'pct')
        
        json_path = output_dir / f"{safe_name}_benchmark_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump([r.to_dict() for r in self.results], f, indent=2, default=str)
        
        csv_path = output_dir / f"{safe_name}_summary_{timestamp}.csv"
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Symbol', 'Timeframe', 'Sample Size', 'Periods',
                'Plot Name', 'Mean', 'StdDev', 'Min', 'Max', 'Last', 'Error'
            ])
            
            for r in self.results:
                for plot_name, stats in r.statistics.items():
                    writer.writerow([
                        r.config.symbol,
                        r.config.timeframe,
                        r.config.sample_size,
                        len(r.periods),
                        plot_name,
                        stats.get('mean'),
                        stats.get('stdev'),
                        stats.get('min'),
                        stats.get('max'),
                        stats.get('last'),
                        r.error or ''
                    ])
        
        success = sum(1 for r in self.results if not r.error)
        print(f"\n{'='*60}")
        print("BENCHMARK COMPLETE")
        print(f"{'='*60}")
        print(f"Total: {len(self.results)}")
        print(f"Success: {success}")
        print(f"Failed: {len(self.results) - success}")
        print(f"Results saved:")
        print(f"  JSON: {json_path}")
        print(f"  CSV: {csv_path}")
        
        if self.study_limit_reached:
            print(f"\nNOTE: Study limit was reached. Wait 3-5 minutes before next run.")


class MultiIndicatorComparison:
    """
    Compare multiple indicators side-by-side.
    
    Processes SEQUENTIALLY to respect free tier limits.
    """
    
    def __init__(self, session: str = None, signature: str = None):
        self.session = session
        self.signature = signature
        self.study_limit_reached = False
        
    async def compare(
        self,
        indicators: List[Tuple[str, str]],
        symbol: str,
        timeframe: str,
        sample_size: int,
        output_dir: str = './comparison_results'
    ):
        """Compare multiple indicators sequentially"""
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n{'='*60}")
        print("MULTI-INDICATOR COMPARISON (Sequential)")
        print(f"{'='*60}")
        print(f"Symbol: {symbol}")
        print(f"Timeframe: {timeframe}")
        print(f"Indicators: {[n for n, _ in indicators]}")
        print(f"\nProcessing sequentially to respect free tier limits...\n")
        
        client = Client(session=self.session, signature=self.signature)
        client.on_error(lambda *err: None)
        await client.connect()
        
        chart = client.Session.Chart()
        chart.set_market(symbol, timeframe=timeframe, range=sample_size)
        
        # Wait for chart
        chart_ready = asyncio.Future()
        def on_ready(changes):
            if chart.periods and not chart_ready.done():
                chart_ready.set_result(True)
        chart.on_update(on_ready)
        
        try:
            await asyncio.wait_for(chart_ready, timeout=15)
            print(f"Chart ready with {len(chart.periods)} periods\n")
        except asyncio.TimeoutError:
            print("Warning: Chart data timeout\n")
        
        # Collect data from each indicator SEQUENTIALLY
        all_data = {}
        
        for name, ind_id in indicators:
            if self.study_limit_reached:
                print(f"Skipping remaining indicators (study limit)")
                break
                
            print(f"Testing {name}...", end=' ', flush=True)
            
            try:
                indicator = await get_indicator(ind_id, session=self.session, signature=self.signature)
                study = chart.Study(indicator)
                
                future = asyncio.Future()
                data = []
                
                def on_update(changes):
                    if study.periods and not future.done():
                        for period in study.periods:
                            data.append({
                                'timestamp': period.get('$time'),
                                'values': {k: v for k, v in period.items() if not k.startswith('$')}
                            })
                        study.remove()
                        future.set_result(True)
                
                def on_error(err):
                    err_msg = str(err)
                    if 'maximum number of studies' in err_msg.lower():
                        self.study_limit_reached = True
                    if not future.done():
                        future.set_result(False)
                
                study.on_update(on_update)
                study.on_error(on_error)
                
                try:
                    await asyncio.wait_for(future, timeout=15)
                    all_data[name] = data
                    print(f"OK ({len(data)} periods)")
                except asyncio.TimeoutError:
                    print("Timeout")
                
            except Exception as e:
                print(f"Error: {e}")
            
            await asyncio.sleep(0.5)
        
        chart.delete()
        await client.end()
        
        # Save results
        await self._save_comparison(all_data, indicators, symbol, timeframe, output_dir)
        
        return all_data
    
    async def _save_comparison(
        self,
        all_data: Dict[str, List],
        indicators: List[Tuple[str, str]],
        symbol: str,
        timeframe: str,
        output_dir: Path
    ):
        """Save comparison results"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        json_path = output_dir / f"comparison_{symbol.replace(':', '_')}_{timeframe}_{timestamp}.json"
        with open(json_path, 'w') as f:
            json.dump({
                'symbol': symbol,
                'timeframe': timeframe,
                'indicators': [n for n, _ in indicators],
                'data': all_data
            }, f, indent=2, default=str)
        
        print(f"\n{'='*60}")
        print("COMPARISON COMPLETE")
        print(f"{'='*60}")
        print(f"Results saved: {json_path}")
        
        if self.study_limit_reached:
            print(f"\nNOTE: Study limit was reached. Not all indicators may have been processed.")


# Indicator ID mapping
INDICATOR_MAP = {
    'RSI': 'STD;RSI',
    'MACD': 'STD;MACD',
    'BB': 'STD;Bollinger_Bands',
    'BOLLINGER': 'STD;Bollinger_Bands',
    'EMA': 'STD;EMA',
    'SMA': 'STD;SMA',
    'VWAP': 'STD;VWAP',
    'ATR': 'STD;Average_True_Range',
    'ADX': 'STD;ADX',
    'STOCH': 'STD;Stochastic',
    'CCI': 'STD;CCI',
    'MFI': 'STD;Money_Flow',
    'OBV': 'STD;On_Balance_Volume',
    'VOLUME': 'STD;Volume',
    'ICHIMOKU': 'STD;Ichimoku%1Cloud',
    'SUPERTREND': 'STD;Supertrend',
    'PSAR': 'STD;PSAR',
}


def resolve_indicator(name: str) -> Tuple[str, str]:
    """Resolve indicator name to ID"""
    name_upper = name.upper()
    if name_upper in INDICATOR_MAP:
        return name, INDICATOR_MAP[name_upper]
    return name, name


async def main():
    parser = argparse.ArgumentParser(
        description='TradingView Indicator Analysis Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan all indicators
    python indicator_analysis.py scan --output ./scan
    
    # Benchmark RSI across assets (sequential processing)
    python indicator_analysis.py benchmark --indicator RSI --assets BTC,ETH --timeframes 15,60
    
    # Compare MACD vs RSI
    python indicator_analysis.py compare --indicators MACD,RSI --symbol BINANCE:BTCUSDT
    
NOTE: Free tier allows only 1-2 studies. This tool processes indicators
sequentially (one at a time) to respect this limit.
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    scan_parser = subparsers.add_parser('scan', help='Scan all indicators')
    scan_parser.add_argument('--output', default='./indicator_scan', help='Output directory')
    
    bench_parser = subparsers.add_parser('benchmark', help='Benchmark indicator')
    bench_parser.add_argument('--indicator', required=True, help='Indicator name')
    bench_parser.add_argument('--assets', default='BINANCE:BTCUSDT', help='Comma-separated assets')
    bench_parser.add_argument('--timeframes', default='60', help='Comma-separated timeframes')
    bench_parser.add_argument('--sample_sizes', default='100', help='Comma-separated sample sizes')
    bench_parser.add_argument('--output', default='./benchmark_results', help='Output directory')
    
    compare_parser = subparsers.add_parser('compare', help='Compare indicators')
    compare_parser.add_argument('--indicators', required=True, help='Comma-separated indicator names')
    compare_parser.add_argument('--symbol', default='BINANCE:BTCUSDT', help='Symbol')
    compare_parser.add_argument('--timeframe', default='60', help='Timeframe')
    compare_parser.add_argument('--sample_size', type=int, default=100, help='Sample size')
    compare_parser.add_argument('--output', default='./comparison_results', help='Output directory')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    session, signature = load_credentials()
    
    if args.command == 'scan':
        scanner = IndicatorScanner()
        scanner.load_builtins()
        scanner.generate_report(args.output)
    
    elif args.command == 'benchmark':
        name, ind_id = resolve_indicator(args.indicator)
        assets = [f"BINANCE:{a}USDT" if not a.startswith('BINANCE:') else a for a in args.assets.split(',')]
        timeframes = args.timeframes.split(',')
        sample_sizes = [int(s) for s in args.sample_sizes.split(',')]
        
        benchmark = IndicatorBenchmark(session, signature)
        await benchmark.run_benchmark(
            name, ind_id, assets, timeframes, sample_sizes, args.output
        )
    
    elif args.command == 'compare':
        ind_names = args.indicators.split(',')
        indicators = [resolve_indicator(n.strip()) for n in ind_names]
        
        comparison = MultiIndicatorComparison(session, signature)
        await comparison.compare(
            indicators, args.symbol, args.timeframe, args.sample_size, args.output
        )


if __name__ == '__main__':
    asyncio.run(main())
