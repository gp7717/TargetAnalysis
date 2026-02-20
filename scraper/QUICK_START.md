# Quick Start Guide

## Installation (One-time setup)

```bash
# Navigate to scraper directory
cd C:\SpacePeppers\SpacePeppers\Target\scraper

# Install dependencies
pip install playwright beautifulsoup4 pandas lxml

# Set up browser driver
python -m playwright install chromium
```

## Running the Scraper

### Option 1: Scrape First Page Only (Quick Test)
```bash
# This will scrape ~24-40 products from first page only
python target_handbags_advanced.py --max-products 40
```

**Output files created in `../output/`:**
- `products.json` - Full product data as JSON
- `products.csv` - Spreadsheet format
- `products.jsonl` - Line-delimited JSON

### Option 2: Scrape Multiple Pages (Best for Full Dataset)
```bash
# Scrapes all available pages with pagination
python target_handbags_advanced.py --max-products 500
```

### Option 3: Scrape with Product Details (Slowest but Most Complete)
```bash
# Visits each product page for full details (2-3x slower)
python target_handbags_advanced.py --max-products 100 --details --delay-min 2 --delay-max 4
```

### Option 4: Verbose Mode (For Debugging)
```bash
# Shows detailed output as it scrapes
python target_handbags_advanced.py --max-products 20 --verbose
```

## Check Output

After scraping, view the collected data:

```bash
# View first few products as JSON
type ..\output\products.json | more

# Open CSV in Excel/Sheets
# Navigate to: ..\output\products.csv

# Count total products scraped
wc -l ..\output\products.jsonl
```

## Adjusting Performance

### Faster Scraping (More Aggressive)
```bash
python target_handbags_advanced.py --max-products 200 --delay-min 0.5 --delay-max 1.0
```
⚠️ May trigger rate limiting

### Slower Scraping (Safer)
```bash
python target_handbags_advanced.py --max-products 200 --delay-min 3 --delay-max 5
```
✓ Less likely to be blocked

## Expected Results

### First Page (~40 products)
- Runtime: ~2-3 minutes
- File size: ~200-300 KB
- Metadata accuracy: 95%+

### All Pages (~1000+ products)
- Runtime: ~1-2 hours (depending on delays)
- File size: ~5-10 MB
- Metadata accuracy: 95%+

### With Details (~100 products)
- Runtime: ~10-15 minutes
- File size: ~2-3 MB
- Includes: images, full specs, highlights

## Data Fields Extracted

Each product record includes:
- ✓ Product ID & URL
- ✓ Brand, Title, Description
- ✓ Current price, regular price, discount %
- ✓ Rating & review count
- ✓ "Bought in last month" count
- ✓ Available colors
- ✓ Product images
- ✓ Stock status
- ✓ Sale/Clearance/New indicators
- ✓ Seller information

## Troubleshooting

### Issue: "Module not found" errors
**Solution:**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Issue: Browser not found
**Solution:**
```bash
python -m playwright install chromium --with-deps
```

### Issue: Getting blocked (429/403 errors)
**Solution:** Increase delays
```bash
python target_handbags_advanced.py --max-products 50 --delay-min 5 --delay-max 10
```

### Issue: Script taking too long
**Solution:** Reduce max-products or disable details
```bash
python target_handbags_advanced.py --max-products 50  # Don't use --details
```

## File Locations

```
C:\SpacePeppers\SpacePeppers\Target\
├── scraper/
│   ├── target_handbags_advanced.py    ← Main scraper
│   ├── QUICK_START.md                 ← This file
│   └── SCRAPER_README.md              ← Full documentation
└── output/
    ├── products.json                  ← Structured data
    ├── products.csv                   ← Spreadsheet format
    └── products.jsonl                 ← Line-delimited JSON
```

## Next Steps

1. **Test the scraper**: Run with `--max-products 20 --verbose`
2. **Check output**: Look at the generated JSON/CSV files
3. **Scale up**: Increase `--max-products` once confident
4. **Store data**: Copy files to database or backup location
5. **Schedule**: Set up Windows Task Scheduler for periodic runs

## Example Commands (Copy & Paste Ready)

```powershell
# Basic test
python target_handbags_advanced.py --max-products 20 --verbose

# First page only
python target_handbags_advanced.py --max-products 40

# Multiple pages
python target_handbags_advanced.py --max-products 200

# Conservative scraping (safe)
python target_handbags_advanced.py --max-products 100 --delay-min 2 --delay-max 4

# With details (slow)
python target_handbags_advanced.py --max-products 50 --details --delay-min 3 --delay-max 5
```

## Support

Check SCRAPER_README.md for:
- Full feature list
- Advanced configuration
- API usage (programmatic access)
- Performance tuning tips
