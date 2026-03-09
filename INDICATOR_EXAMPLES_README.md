# TradingView Indicator Examples - Comprehensive Guide

This directory contains comprehensive examples for testing and analyzing TradingView indicators across multiple assets, timeframes, and configurations.

## Files Overview

| File | Description |
|------|-------------|
| `indicator_examples.py` | Test all major indicator categories with various configurations |
| `indicator_analysis.py` | Advanced analysis tools: benchmarking, comparison, scanning |
| `indicator_outputs_demo.py` | Post-processing tools for saved results |
| `test_single_indicator.py` | Simple single-indicator test script |
| `example_study_management.py` | How to check and remove studies on a chart |
| `study_management_example.py` | Advanced study management patterns |

---

## ⚠️ CRITICAL: Free Tier Usage Guide

TradingView's **free tier has strict limitations** that affect how you must use these tools:

### Free Tier Limits
- **1-2 studies per chart maximum**
- Study count persists on TradingView's servers for **several minutes**
- No way to force-clear studies from client side

### The Solution: Sequential Processing

All tools in this package use **SEQUENTIAL PROCESSING**:

```
┌─────────────────────────────────────────────────────────────┐
│  CORRECT Pattern (Free Tier Friendly)                       │
├─────────────────────────────────────────────────────────────┤
│  1. Create ONE client                                       │
│  2. Create ONE chart                                        │
│  3. For each indicator:                                     │
│     a. Fetch indicator metadata                             │
│     b. Create ONE study                                     │
│     c. Wait for data (up to 15 seconds)                     │
│     d. IMMEDIATELY remove study: study.remove()             │
│     e. Wait 0.5-1 second                                    │
│     f. Proceed to next indicator                            │
│  4. Cleanup: chart.delete(), client.end()                   │
└─────────────────────────────────────────────────────────────┘
```

### What NOT to Do (Will Hit Limits)

```python
# ❌ WRONG: Creating multiple studies without removal
study1 = chart.Study(indic1)  # Study 1
study2 = chart.Study(indic2)  # Study 2 - MAY FAIL (limit reached)
study3 = chart.Study(indic3)  # Study 3 - WILL FAIL

# ❌ WRONG: Not removing studies
study = chart.Study(indic)
# ... wait for data ...
# Missing: study.remove()  <- DON'T FORGET THIS!

# ❌ WRONG: Rapid-fire study creation
for indic in indicators:
    study = chart.Study(indic)  # Too fast!
    # Need delay between studies
```

### If You Hit the Study Limit

If you see: `"The maximum number of studies per chart has been reached for current subscription"`

1. **Wait 3-5 minutes** - The server will automatically clean up
2. **Reduce test scope** - Test fewer indicators at once
3. **Use single indicator test** - Use `test_single_indicator.py` for quick tests
4. **Check and remove studies** - Use the study management methods (see below)

---

## Study Management

The `ChartSession` class provides methods to check and manage studies:

### List Active Studies

```python
chart = client.Session.Chart()
chart.set_market('BINANCE:BTCUSDT', timeframe='60')

# Get list of active studies
studies = chart.get_studies()
print(f"Active studies: {len(studies)}")
for study in studies:
    print(f"  - {study['id']}")
```

### Remove a Specific Study

```python
# Remove by study ID
removed = chart.remove_study('st_abc123')
print(f"Removed: {removed}")  # True if found, False otherwise

# Or remove via study object
study = chart.Study(indicator)
# ... use study ...
study.remove()  # Recommended approach
```

### Remove All Studies

```python
# Remove all studies at once
removed = await chart.remove_all_studies()
print(f"Removed {removed} studies")

# Or simply delete the chart (nuclear option)
chart.delete()  # Removes chart and all studies
chart = client.Session.Chart()  # Create fresh chart
```

### Complete Example

See `example_study_management.py` for a complete working example:

```bash
python example_study_management.py
```

Output:
```
STUDY MANAGEMENT EXAMPLE
============================================================

1. Connecting to TradingView...
   Connected!

2. Creating chart...
   Chart ready with 50 periods

3. Checking active studies...
   Active studies: 0

4. Adding studies...
   Added SMA: st_abc123
   Added RSI: st_def456

5. Checking active studies...
   Active studies: 2
     - st_abc123
     - st_def456

6. Removing SMA (st_abc123)...
   Removed via study.remove()
   Remaining studies: 1

7. Removing all remaining studies...
   Removed 1 studies

8. Final study count...
   Active studies: 0
```

---

## indicator_examples.py

Test all major built-in indicator categories.

### Usage

```bash
# Test moving averages (sequential processing)
python indicator_examples.py moving_averages --symbol BINANCE:BTCUSDT --timeframe 60

# Test with smaller sample (faster)
python indicator_examples.py oscillators --symbol BINANCE:BTCUSDT --timeframe 60 --sample_size 50

# Test on multiple assets (slower, higher chance of hitting limits)
python indicator_examples.py trend --symbol BINANCE:BTCUSDT --timeframe 240 --sample_size 200

# If you hit limits, wait and try with fewer indicators
python indicator_examples.py moving_averages --symbol BINANCE:BTCUSDT --sample_size 50
```

### Indicator Categories

| Category | Indicators |
|----------|-----------|
| `moving_averages` | SMA, EMA, WMA, VWAP, Hull MA, ALMA, KAMA, DEMA, TEMA |
| `oscillators` | RSI, MACD, Stochastic, CCI, MFI, Williams %R, Awesome Oscillator |
| `volume` | Volume, OBV, VWMA, Accumulation/Distribution, Chaikin Money Flow |
| `trend` | ADX, Supertrend, Ichimoku Cloud, Parabolic SAR, Aroon |
| `volatility` | Bollinger Bands, ATR, Keltner Channels, Donchian Channels |
| `candlestick` | Doji, Engulfing, Hammer, Shooting Star, Harami patterns |

### Output

Results are saved to:
- `indicator_results/{category}_results_{timestamp}.json` - Full data
- `indicator_results/{category}_results_{timestamp}.csv` - Summary statistics

---

## indicator_analysis.py

Advanced analysis with benchmarking and comparison tools.

### Commands

#### 1. Scan - Categorize all built-in indicators

```bash
python indicator_analysis.py scan --output ./indicator_scan
```

Output:
- `indicator_scan/indicator_scan_{timestamp}.json` - Full catalog

#### 2. Benchmark - Test indicator across configurations

```bash
# Benchmark RSI on single asset
python indicator_analysis.py benchmark \
    --indicator RSI \
    --assets BINANCE:BTCUSDT \
    --timeframes 15,60,240 \
    --sample_sizes 50,100

# Benchmark on multiple assets (sequential processing)
python indicator_analysis.py benchmark \
    --indicator MACD \
    --assets BTC,ETH \
    --timeframes 60 \
    --sample_sizes 100
```

#### 3. Compare - Side-by-side indicator comparison

```bash
# Compare two indicators (sequential)
python indicator_analysis.py compare \
    --indicators MACD,RSI \
    --symbol BINANCE:BTCUSDT \
    --timeframe 60 \
    --sample_size 100

# Compare multiple indicators
python indicator_analysis.py compare \
    --indicators RSI,MACD,BB \
    --symbol BINANCE:BTCUSDT \
    --timeframe 240
```

---

## test_single_indicator.py

Simple script for testing a single indicator - useful for quick tests without batch overhead.

### Usage

```bash
# Test SMA
python test_single_indicator.py STD;SMA

# Test RSI
python test_single_indicator.py STD;RSI

# Test custom indicator (if you have SESSION/SIGNATURE)
python test_single_indicator.py USER;your_indicator_id
```

---

## Example Workflows

### Workflow 1: Testing a New Indicator

```bash
# Step 1: Test single indicator first
python test_single_indicator.py STD;SMA

# If successful, proceed to category test
python indicator_examples.py moving_averages --symbol BINANCE:BTCUSDT --timeframe 60 --sample_size 50

# If you hit study limit, wait 3-5 minutes and continue
sleep 180  # Wait 3 minutes
python indicator_examples.py moving_averages --symbol BINANCE:ETHUSDT --timeframe 60 --sample_size 50
```

### Workflow 2: Benchmarking Strategy

```bash
# Step 1: Benchmark on small sample first
python indicator_analysis.py benchmark \
    --indicator RSI \
    --assets BTC \
    --timeframes 60 \
    --sample_sizes 50

# Step 2: If successful, expand
python indicator_analysis.py benchmark \
    --indicator RSI \
    --assets BTC,ETH \
    --timeframes 15,60,240 \
    --sample_sizes 50,100,200
```

### Workflow 3: Multi-Timeframe Analysis

```bash
# Compare indicators across timeframes
python indicator_analysis.py compare \
    --indicators RSI,MACD \
    --symbol BINANCE:BTCUSDT \
    --timeframe 60 \
    --sample_size 200

# Wait, then test different timeframe
sleep 180
python indicator_analysis.py compare \
    --indicators RSI,MACD \
    --symbol BINANCE:BTCUSDT \
    --timeframe 240 \
    --sample_size 200
```

---

## Implementation Details

### Sequential Processing Pattern

Here's how the tools implement free-tier-friendly sequential processing:

```python
async def test_indicators_sequential(indicators):
    # Create ONE client
    client = Client(session=session, signature=signature)
    await client.connect()
    
    # Create ONE chart
    chart = client.Session.Chart()
    chart.set_market('BINANCE:BTCUSDT', timeframe='60', range=100)
    
    # Wait for chart data
    await wait_for_chart(chart)
    
    # Process indicators ONE AT A TIME
    for name, ind_id in indicators:
        # Fetch indicator metadata
        indicator = await get_indicator(ind_id)
        
        # Create study
        study = chart.Study(indicator)
        
        # Wait for data
        await wait_for_data(study, timeout=15)
        
        # IMMEDIATELY remove study
        study.remove()
        
        # Brief pause before next
        await asyncio.sleep(0.5)
    
    # Cleanup
    chart.delete()
    await client.end()
```

### Error Handling

All tools handle these error conditions:

1. **Study limit reached** - Captured, reported, processing continues
2. **Timeout** - 15-second default, configurable
3. **Indicator not found** - Graceful skip with error message
4. **Network errors** - Retries with exponential backoff

---

## Troubleshooting

### "Maximum number of studies reached"

**Solution:**
```bash
# Wait 3-5 minutes
sleep 300

# Try again with fewer indicators
python test_single_indicator.py STD;SMA
```

### "Timeout waiting for indicator data"

**Solutions:**
- Check your internet connection
- Try a different symbol (some may be unavailable)
- Increase timeout (modify script)
- Check if SESSION/SIGNATURE are valid

### "Inexistent or unsupported indicator"

**Solution:**
- Verify indicator ID from `builtins.json`
- Use correct format: `STD;SMA`, `STD;RSI`, etc.

---

## Asset Symbols Reference

### Cryptocurrency (Binance)
- `BINANCE:BTCUSDT` - Bitcoin
- `BINANCE:ETHUSDT` - Ethereum
- `BINANCE:SOLUSDT` - Solana
- `BINANCE:XRPUSDT` - Ripple

### Forex (OANDA)
- `OANDA:EURUSD` - Euro/USD
- `OANDA:GBPUSD` - GBP/USD
- `OANDA:USDJPY` - USD/JPY
- `OANDA:XAUUSD` - Gold

### Indices (OANDA)
- `OANDA:SPX500USD` - S&P 500
- `OANDA:NAS100USD` - Nasdaq 100

---

## Timeframe Reference

| Code | Description |
|------|-------------|
| 1    | 1 minute |
| 5    | 5 minutes |
| 15   | 15 minutes |
| 60   | 1 hour |
| 240  | 4 hours |
| 1D   | Daily |

---

## Environment Setup

Create a `.env` file:

```bash
SESSION=your_session_cookie_here
SIGNATURE=your_signature_cookie_here
TV_USER=your_username
```

Or set environment variables:

```bash
export SESSION="your_session_cookie"
export SIGNATURE="your_signature_cookie"
```

---

## Summary

| What | How |
|------|-----|
| **Free tier limit** | 1-2 studies per chart |
| **Solution** | Sequential processing (one at a time) |
| **Key pattern** | Create → Wait → Remove → Pause → Next |
| **If limit hit** | Wait 3-5 minutes or use `chart.remove_all_studies()` |
| **Best practice** | Start with single indicator tests |
| **Check studies** | `chart.get_studies()` |
| **Remove study** | `study.remove()` or `chart.remove_study(id)` |
| **Remove all** | `await chart.remove_all_studies()` |
