#!/usr/bin/env python3
"""
Indicator Outputs Demo & Analysis
==================================

Demonstrates how to work with indicator output files and perform analysis:
- Load and parse JSON/CSV results
- Calculate statistics and correlations
- Generate summary reports
- Export to various formats

This file works with outputs from indicator_examples.py and indicator_analysis.py

Usage:
    python indicator_outputs_demo.py [action] [options]

Actions:
    analyze     - Analyze saved indicator results
    summarize   - Create summary report across multiple results
    correlate   - Find correlations between indicators
    export      - Export to different formats (Excel, Markdown)
    visualize   - Generate data for visualization

Examples:
    # Analyze a single result file
    python indicator_outputs_demo.py analyze --file ./indicator_results/oscillators_results_20240115_120000.json
    
    # Summarize all results in a directory
    python indicator_outputs_demo.py summarize --dir ./indicator_results --output ./summary_report.md
    
    # Find correlations between indicators
    python indicator_outputs_demo.py correlate --files file1.json,file2.json --output correlations.csv
"""

import json
import csv
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import defaultdict
import statistics


def load_json_results(filepath: str) -> Dict:
    """Load results from JSON file"""
    with open(filepath) as f:
        return json.load(f)


def load_csv_results(filepath: str) -> List[Dict]:
    """Load results from CSV file"""
    with open(filepath) as f:
        reader = csv.DictReader(f)
        return list(reader)


def analyze_indicator_result(data: Dict or List) -> Dict:
    """
    Analyze indicator result data and generate statistics
    
    Returns dict with:
    - summary: Basic info (indicator name, symbol, timeframe, etc.)
    - statistics: Statistical analysis of each plot
    - trends: Trend direction for each plot
    - divergences: Potential divergences detected
    """
    analysis = {
        'summary': {},
        'statistics': {},
        'trends': {},
        'signals': []
    }
    
    # Handle different data formats
    if isinstance(data, list):
        # List of IndicatorResult objects
        return analyze_multiple_results(data)
    
    # Single result object
    if 'config' in data:
        # AnalysisResult format
        config = data['config']
        analysis['summary'] = {
            'indicator': config.get('indicator_name'),
            'symbol': config.get('symbol'),
            'timeframe': config.get('timeframe'),
            'sample_size': config.get('sample_size'),
            'periods_collected': len(data.get('periods', []))
        }
        
        periods = data.get('periods', [])
        if periods:
            # Analyze each plot
            plot_keys = set()
            for p in periods:
                plot_keys.update(p.get('indicator_values', {}).keys())
            
            for key in plot_keys:
                values = [
                    p['indicator_values'].get(key)
                    for p in periods
                    if key in p.get('indicator_values', {})
                ]
                values = [v for v in values if v is not None and isinstance(v, (int, float))]
                
                if values:
                    analysis['statistics'][key] = calculate_statistics(values)
                    analysis['trends'][key] = determine_trend(values)
    
    elif 'indicator_name' in data:
        # IndicatorResult format
        analysis['summary'] = {
            'indicator': data.get('indicator_name'),
            'symbol': data.get('symbol'),
            'timeframe': data.get('timeframe'),
            'sample_size': data.get('sample_size'),
            'periods_collected': data.get('periods_count')
        }
        
        plots = data.get('plots', {})
        for key, value in plots.items():
            if isinstance(value, (int, float)):
                analysis['statistics'][key] = {'last': value}
    
    return analysis


def analyze_multiple_results(results: List[Dict]) -> Dict:
    """Analyze multiple indicator results"""
    analysis = {
        'summary': {
            'total_tests': len(results),
            'successful': sum(1 for r in results if not r.get('error')),
            'failed': sum(1 for r in results if r.get('error'))
        },
        'by_indicator': defaultdict(list),
        'by_symbol': defaultdict(list),
        'by_timeframe': defaultdict(list)
    }
    
    for result in results:
        ind_name = result.get('indicator_name', 'Unknown')
        symbol = result.get('symbol', 'Unknown')
        tf = result.get('timeframe', 'Unknown')
        
        analysis['by_indicator'][ind_name].append(result)
        analysis['by_symbol'][symbol].append(result)
        analysis['by_timeframe'][tf].append(result)
    
    # Convert defaultdict to regular dict for JSON serialization
    analysis['by_indicator'] = dict(analysis['by_indicator'])
    analysis['by_symbol'] = dict(analysis['by_symbol'])
    analysis['by_timeframe'] = dict(analysis['by_timeframe'])
    
    return analysis


def calculate_statistics(values: List[float]) -> Dict:
    """Calculate statistical measures"""
    if not values:
        return {}
    
    stats = {
        'count': len(values),
        'mean': statistics.mean(values),
        'stdev': statistics.stdev(values) if len(values) > 1 else 0,
        'min': min(values),
        'max': max(values),
        'last': values[-1],
        'range': max(values) - min(values)
    }
    
    # Calculate percentiles
    sorted_vals = sorted(values)
    stats['median'] = sorted_vals[len(sorted_vals) // 2]
    stats['p25'] = sorted_vals[len(sorted_vals) // 4]
    stats['p75'] = sorted_vals[3 * len(sorted_vals) // 4]
    
    return stats


def determine_trend(values: List[float], period: int = 10) -> str:
    """Determine trend direction"""
    if len(values) < period * 2:
        return 'insufficient_data'
    
    recent = values[-period:]
    previous = values[-(period*2):-period]
    
    recent_avg = sum(recent) / len(recent)
    previous_avg = sum(previous) / len(previous)
    
    change_pct = ((recent_avg - previous_avg) / abs(previous_avg)) * 100 if previous_avg != 0 else 0
    
    if change_pct > 5:
        return 'strong_up'
    elif change_pct > 1:
        return 'up'
    elif change_pct < -5:
        return 'strong_down'
    elif change_pct < -1:
        return 'down'
    else:
        return 'sideways'


def generate_markdown_report(analysis: Dict, output_path: str):
    """Generate Markdown report from analysis"""
    
    lines = [
        "# Indicator Analysis Report",
        "",
        f"Generated: {datetime.now().isoformat()}",
        "",
        "## Summary",
        "",
    ]
    
    summary = analysis.get('summary', {})
    for key, value in summary.items():
        lines.append(f"- **{key.replace('_', ' ').title()}**: {value}")
    
    lines.extend(["", "## Statistics", ""])
    
    statistics = analysis.get('statistics', {})
    if statistics:
        lines.append("| Plot | Mean | StdDev | Min | Max | Last | Trend |")
        lines.append("|------|------|--------|-----|-----|------|-------|")
        
        for plot_name, stats in statistics.items():
            trend = analysis.get('trends', {}).get(plot_name, 'unknown')
            lines.append(
                f"| {plot_name} | "
                f"{stats.get('mean', 0):.4f} | "
                f"{stats.get('stdev', 0):.4f} | "
                f"{stats.get('min', 0):.4f} | "
                f"{stats.get('max', 0):.4f} | "
                f"{stats.get('last', 0):.4f} | "
                f"{trend} |"
            )
    
    lines.extend(["", "## Detailed Results", ""])
    
    # Add by-indicator breakdown
    by_indicator = analysis.get('by_indicator', {})
    if by_indicator:
        lines.append("### Results by Indicator")
        lines.append("")
        for ind_name, results in by_indicator.items():
            lines.append(f"#### {ind_name}")
            lines.append(f"- Tests: {len(results)}")
            success = sum(1 for r in results if not r.get('error'))
            lines.append(f"- Success: {success}/{len(results)}")
            lines.append("")
    
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))
    
    print(f"Report saved: {output_path}")


def correlate_indicators(file1: str, file2: str) -> Dict:
    """Calculate correlation between two indicator results"""
    
    data1 = load_json_results(file1)
    data2 = load_json_results(file2)
    
    # Extract time series
    def extract_series(data):
        if isinstance(data, list):
            data = data[0]  # Use first result
        
        periods = data.get('periods', [])
        series = defaultdict(list)
        
        for p in periods:
            ts = p.get('timestamp')
            for key, value in p.get('indicator_values', {}).items():
                if isinstance(value, (int, float)):
                    series[key].append((ts, value))
        
        return series
    
    series1 = extract_series(data1)
    series2 = extract_series(data2)
    
    correlations = {}
    
    # Find common timestamps and calculate correlation
    for key1, vals1 in series1.items():
        for key2, vals2 in series2.items():
            # Create timestamp -> value maps
            map1 = {ts: v for ts, v in vals1}
            map2 = {ts: v for ts, v in vals2}
            
            # Find common timestamps
            common_ts = set(map1.keys()) & set(map2.keys())
            
            if len(common_ts) > 10:  # Need enough data points
                x = [map1[ts] for ts in sorted(common_ts)]
                y = [map2[ts] for ts in sorted(common_ts)]
                
                # Calculate Pearson correlation
                if len(x) > 1 and len(y) > 1:
                    try:
                        mean_x = sum(x) / len(x)
                        mean_y = sum(y) / len(y)
                        
                        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
                        denom_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
                        denom_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
                        
                        if denom_x > 0 and denom_y > 0:
                            corr = numerator / (denom_x * denom_y)
                            correlations[f"{key1}_vs_{key2}"] = corr
                    except:
                        pass
    
    return correlations


def export_to_excel_format(data: Dict, output_path: str):
    """Export data to CSV format (Excel-compatible)"""
    
    if 'periods' in data:
        periods = data['periods']
        
        with open(output_path, 'w', newline='') as f:
            if periods:
                # Get all possible columns
                columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                for p in periods:
                    columns.extend(p.get('indicator_values', {}).keys())
                columns = list(dict.fromkeys(columns))  # Remove duplicates
                
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                
                for p in periods:
                    row = {
                        'timestamp': p.get('timestamp'),
                        'open': p.get('open'),
                        'high': p.get('high'),
                        'low': p.get('low'),
                        'close': p.get('close'),
                        'volume': p.get('volume'),
                    }
                    row.update(p.get('indicator_values', {}))
                    writer.writerow(row)
        
        print(f"Excel-compatible CSV saved: {output_path}")


def create_visualization_data(data: Dict, output_path: str):
    """Create JSON format optimized for visualization libraries"""
    
    viz_data = {
        'metadata': {
            'title': data.get('config', {}).get('indicator_name', 'Unknown'),
            'symbol': data.get('config', {}).get('symbol'),
            'timeframe': data.get('config', {}).get('timeframe'),
            'generated': datetime.now().isoformat()
        },
        'series': []
    }
    
    periods = data.get('periods', [])
    
    # Extract price data
    if periods:
        price_series = {
            'name': 'Price',
            'type': 'candlestick',
            'data': [
                {
                    'x': p.get('timestamp'),
                    'o': p.get('open'),
                    'h': p.get('high'),
                    'l': p.get('low'),
                    'c': p.get('close')
                }
                for p in periods
            ]
        }
        viz_data['series'].append(price_series)
        
        # Extract indicator plots
        plot_names = set()
        for p in periods:
            plot_names.update(p.get('indicator_values', {}).keys())
        
        for plot_name in plot_names:
            series = {
                'name': plot_name,
                'type': 'line',
                'data': [
                    {
                        'x': p.get('timestamp'),
                        'y': p.get('indicator_values', {}).get(plot_name)
                    }
                    for p in periods
                    if plot_name in p.get('indicator_values', {})
                ]
            }
            viz_data['series'].append(series)
    
    with open(output_path, 'w') as f:
        json.dump(viz_data, f, indent=2)
    
    print(f"Visualization data saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Indicator Outputs Demo & Analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Analyze single file
    python indicator_outputs_demo.py analyze --file results.json
    
    # Summarize directory
    python indicator_outputs_demo.py summarize --dir ./results --format markdown
    
    # Correlate two indicators
    python indicator_outputs_demo.py correlate --files rsi.json,macd.json --output corr.json
    
    # Export to Excel format
    python indicator_outputs_demo.py export --file results.json --format excel
    
    # Create visualization data
    python indicator_outputs_demo.py visualize --file results.json --output chart_data.json
        """
    )
    
    subparsers = parser.add_subparsers(dest='action')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze result file')
    analyze_parser.add_argument('--file', required=True, help='JSON result file')
    analyze_parser.add_argument('--output', help='Output file for analysis')
    
    # Summarize command
    summarize_parser = subparsers.add_parser('summarize', help='Summarize directory')
    summarize_parser.add_argument('--dir', required=True, help='Directory with result files')
    summarize_parser.add_argument('--format', choices=['json', 'markdown'], default='json')
    summarize_parser.add_argument('--output', required=True, help='Output file')
    
    # Correlate command
    correlate_parser = subparsers.add_parser('correlate', help='Correlate indicators')
    correlate_parser.add_argument('--files', required=True, help='Comma-separated file paths')
    correlate_parser.add_argument('--output', required=True, help='Output file')
    
    # Export command
    export_parser = subparsers.add_parser('export', help='Export to format')
    export_parser.add_argument('--file', required=True, help='Input file')
    export_parser.add_argument('--format', choices=['excel', 'json'], default='excel')
    export_parser.add_argument('--output', required=True, help='Output file')
    
    # Visualize command
    viz_parser = subparsers.add_parser('visualize', help='Create visualization data')
    viz_parser.add_argument('--file', required=True, help='Input file')
    viz_parser.add_argument('--output', required=True, help='Output file')
    
    args = parser.parse_args()
    
    if not args.action:
        parser.print_help()
        return
    
    if args.action == 'analyze':
        data = load_json_results(args.file)
        analysis = analyze_indicator_result(data)
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(analysis, f, indent=2)
            print(f"Analysis saved: {args.output}")
        else:
            print(json.dumps(analysis, indent=2))
    
    elif args.action == 'summarize':
        # Load all JSON files in directory
        results = []
        for filepath in Path(args.dir).glob('*.json'):
            try:
                data = load_json_results(str(filepath))
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except Exception as e:
                print(f"Warning: Could not load {filepath}: {e}")
        
        analysis = analyze_multiple_results(results)
        
        if args.format == 'markdown':
            generate_markdown_report(analysis, args.output)
        else:
            with open(args.output, 'w') as f:
                json.dump(analysis, f, indent=2)
            print(f"Summary saved: {args.output}")
    
    elif args.action == 'correlate':
        files = args.files.split(',')
        if len(files) != 2:
            print("Error: Please provide exactly 2 files for correlation")
            return
        
        correlations = correlate_indicators(files[0], files[1])
        
        with open(args.output, 'w') as f:
            json.dump(correlations, f, indent=2)
        
        print(f"Correlations saved: {args.output}")
        print("\nTop correlations:")
        for name, corr in sorted(correlations.items(), key=lambda x: abs(x[1]), reverse=True)[:10]:
            print(f"  {name}: {corr:.4f}")
    
    elif args.action == 'export':
        data = load_json_results(args.file)
        
        if args.format == 'excel':
            export_to_excel_format(data, args.output)
        else:
            with open(args.output, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"Exported: {args.output}")
    
    elif args.action == 'visualize':
        data = load_json_results(args.file)
        create_visualization_data(data, args.output)


if __name__ == '__main__':
    main()
