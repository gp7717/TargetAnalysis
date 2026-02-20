# TargetAnalysis

Target handbags scraper and Chroma DB ingest with CLIP text (+ image) embeddings.

## Chroma DB ingest (CLIP embeddings)

The script `scripts/ingest_handbags_to_chroma.py` loads handbags JSON/CSV, builds document text per product, embeds with CLIP (ViT-B/32), and uploads to **Chroma Cloud**.

### Environment variables

Copy `.env.example` to `.env` and set:

- **`CHROMA_API_KEY`** (required): Your Chroma Cloud API key.
- **`CHROMA_TENANT`** (optional): Tenant ID if your key is scoped to a tenant.
- **`CHROMA_DATABASE`** (optional): Database name if your key is scoped to a database.

### Dependencies

```bash
pip install -r requirements.txt
# CLIP (no PyPI package):
pip install git+https://github.com/openai/CLIP.git
```

PyTorch/CUDA: install separately if you want GPU (e.g. `pip install torch torchvision` with the right CUDA version).

### Run ingest

```bash
# From project root (Target/)
python scripts/ingest_handbags_to_chroma.py
# Or with explicit input and collection:
python scripts/ingest_handbags_to_chroma.py output/target_handbags_20260220_180219.json --collection target_handbags
```

Default input: `output/target_handbags_20260220_180219.json`. Supports `.json`, `.jsonl`, and `.csv`.

---

## Gap analysis (clustering + report)

The script `scripts/run_gap_analysis.py` runs internal gap analysis on handbags data **without** competitor data: style clustering (K-Means/HDBSCAN), PCA/UMAP, price segmentation, rating×review quadrants, brand dominance, color diversity, title-keyword co-occurrence, and six practical gap analyses (SKU density map, rating-weighted strength, new vs established, bestseller gap, clearance pattern, in-stock pressure). Outputs an enriched CSV/JSON and a markdown report.

**Requires:** Same as ingest (PyTorch, CLIP) plus `scikit-learn`, `hdbscan`, `umap-learn` (see `requirements.txt`).

```bash
# From project root
python scripts/run_gap_analysis.py output/target_handbags_20260220_213726.csv
# Options: -o OUTPUT_DIR, -k N_CLUSTERS, --no-hdbscan, --no-umap, --review-high N
# Use --quick-test to run without PyTorch/CLIP (TF-IDF embeddings; good for CI/smoke test).
```

Default output directory: `output/`. Files: `gap_analysis_handbags_YYYYMMDD_HHMMSS.csv`, `.json`, and `_report.md`.

---

## Push to GitHub

```bash
echo "# TargetAnalysis" >> README.md
git init
git add README.md
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/gp7717/TargetAnalysis.git
git push -u origin main
```

To add the whole project instead of only README: `git add .` then commit (ensure `.gitignore` is in place so secrets and venv are not committed).
