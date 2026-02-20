# Gap Analysis Report

Generated: 2026-02-20T23:00:35.191204
Input: C:\D Volume\SpacePeppers\seleric_data_pipeline\TargetAnalysis\output\target_handbags_20260220_213726.csv
Products: 10

---

## 1. Summary

- **Products:** 10
- **Style clusters (K-Means k=5):** 5
- **Price bands:** 5 (0-20, 20-40, 40-70, 70-120, 120+ + unknown)

---

## 2. Style clusters (SKU count, avg price, avg rating, dominant brand)

- **Cluster 0:** SKUs=2, avg_price=37.5, avg_rating=4.60, top_brand=Vera Bradley
- **Cluster 1:** SKUs=3, avg_price=21.2, avg_rating=4.80, top_brand=A New Day
- **Cluster 2:** SKUs=3, avg_price=29.0, avg_rating=4.47, top_brand=Champion
- **Cluster 3:** SKUs=1, avg_price=—, avg_rating=4.60, top_brand=JanSport
- **Cluster 4:** SKUs=1, avg_price=90.3, avg_rating=—, top_brand=Kipling

---

## 3. SKU density (cluster × price band)

```
price_band      0-20  20-40  40-70  70-120  unknown  All
cluster_kmeans                                          
0                  0      1      1       0        0    2
1                  1      2      0       0        0    3
2                  1      2      0       0        0    3
3                  0      0      0       0        1    1
4                  0      0      0       1        0    1
All                2      5      1       1        1   10
```

*(Empty or near-zero cells = price–style gap)*

---

## 4. Rating × review quadrant

- **Proven winner:** 5
- **Hidden opportunity:** 3
- **Weak:** 2

Hidden winners (high rating, low reviews) by cluster:

- Cluster 1: 2
- Cluster 2: 1

---

## 5. Brand dominance (per cluster)

- **Cluster 0:** top brand share = 100% — dominance
- **Cluster 1:** top brand share = 67% — mixed/white-space
- **Cluster 2:** top brand share = 33% — mixed/white-space
- **Cluster 3:** top brand share = 100% — dominance
- **Cluster 4:** top brand share = 100% — dominance

---

## 6. Color diversity (by cluster)

- **Cluster 0:** avg color_count=3.5, main families: {'unknown': 1, 'pastel': 1}
- **Cluster 1:** avg color_count=0.7, main families: {'unknown': 2, 'black': 1}
- **Cluster 2:** avg color_count=4.0, main families: {'black': 2, 'pastel': 1}
- **Cluster 3:** avg color_count=1.0, main families: {'pastel': 1}
- **Cluster 4:** avg color_count=0.0, main families: {'unknown': 1}

---

## 7. Title keyword co-occurrence (gaps)

Top pairs (count):
- tote + quilted: 1
- tote + mini: 1
- tote + drawstring: 1
- backpack + laptop: 1
- crossbody + convertible: 1

Gaps (zero or sparse):
- tote + quilted: 1
- tote + mini: 1
- tote + drawstring: 1
- backpack + laptop: 1
- crossbody + convertible: 1
- crossbody + faux leather: 1
- convertible + faux leather: 1
- quilted + drawstring: 1
- tote + clutch: 0
- tote + backpack: 0
- tote + crossbody: 0
- tote + convertible: 0
- tote + faux leather: 0
- tote + laptop: 0
- tote + organizer: 0
- clutch + backpack: 0
- clutch + crossbody: 0
- clutch + convertible: 0
- clutch + quilted: 0
- clutch + faux leather: 0
- clutch + laptop: 0
- clutch + organizer: 0
- clutch + mini: 0
- clutch + drawstring: 0
- backpack + crossbody: 0
- backpack + convertible: 0
- backpack + quilted: 0
- backpack + faux leather: 0
- backpack + organizer: 0
- backpack + mini: 0
- backpack + drawstring: 0
- crossbody + quilted: 0
- crossbody + laptop: 0
- crossbody + organizer: 0
- crossbody + mini: 0
- crossbody + drawstring: 0
- convertible + quilted: 0
- convertible + laptop: 0
- convertible + organizer: 0
- convertible + mini: 0
- convertible + drawstring: 0
- quilted + faux leather: 0
- quilted + laptop: 0
- quilted + organizer: 0
- quilted + mini: 0
- faux leather + laptop: 0
- faux leather + organizer: 0
- faux leather + mini: 0
- faux leather + drawstring: 0
- laptop + organizer: 0
- laptop + mini: 0
- laptop + drawstring: 0
- organizer + mini: 0
- organizer + drawstring: 0
- mini + drawstring: 0

---

## 8. Six gap analyses

### 8.1 Rating-weighted cluster strength

```
                cluster_score  sku_count
cluster_kmeans                          
3                   27.063283          1
0                   19.783529          2
1                   12.525301          3
2                   10.426761          3
4                    0.000000          1
```

- High score + low SKU count → expand. Low score + high SKU count → over-indexed.

### 8.2 New vs established

```
cluster_kmeans
0    0
1    0
2    0
3    0
4    1
```

- If new SKUs concentrated in one cluster → not innovating in other styles.

### 8.3 Bestseller gap

No best_seller=True in dataset.

### 8.4 Clearance pattern

```
cluster_kmeans
0     0.000000
1    33.333333
2     0.000000
3     0.000000
4     0.000000
```

- High clearance % in a cluster → possible weak demand.

### 8.5 In-stock pressure

```
cluster_kmeans
0    0.0
1    0.0
2    0.0
3    0.0
4    0.0
```

- High out-of-stock % → demand signal.

---

*Internal trend map; competitor comparison when data available.*
