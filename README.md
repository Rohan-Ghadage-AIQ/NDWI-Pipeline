# 🌊 Sentinel-2 NDWI Pipeline — Benchmarked Geospatial Processing

![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![GDAL/Rasterio](https://img.shields.io/badge/GDAL-Rasterio-green)
![Xarray/DataCube](https://img.shields.io/badge/Xarray-DataCube-blueviolet)

A modular, production-ready Python CLI tool that aggregates Sentinel-2 multi-band GeoTIFF images into a **STAC catalog** and computes the **Normalized Difference Water Index (NDWI)** via an xarray DataCube — with built-in performance benchmarking to compare against standard file-by-file processing.

---

## 📁 Project Structure

```
NDWI/
│
├── ndwi_pipeline.py          # Main pipeline script (entry point)
├── requirements.txt          # Python package dependencies
├── .gitignore                # Git ignore rules for data and outputs
├── README.md                 # This documentation file
│
├── sentinel2_images/         # 📥 INPUT — Place your GeoTIFF files here
│   ├── S2_2024_01_02.tif
│   └── ...                   #    (any number of multi-band .tif files)
│
└── output/                   # 📤 OUTPUT — Generated automatically
    ├── ndwi_individual/      # Method A output GeoTIFFs
    ├── ndwi_datacube/        # Method B output GeoTIFFs
    └── stac_item_collection.json # Method B STAC metadata catalog
```

> **Note:** The `sentinel2_images/` folder is where you place your raw data.  
> The `output/` folder (and its subfolders) are created automatically by the script.

---

## 🏗️ Architecture Overview

The pipeline follows a strict **two-step architecture**, each independently benchmarked:

```
┌─────────────────────────────────────────────────────────────────┐
│                      ndwi_pipeline.py                           │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  METHOD A: Individual File Processing (Baseline)          │  │
│  │                                                           │  │
│  │  Process: For each GeoTIFF file independently:            │  │
│  │    1. Load with rasterio                                  │  │
│  │    2. Extract Green & NIR bands                           │  │
│  │    3. Compute NDWI and save                               │  │
│  │  Benchmark: ⏱ time.perf_counter + 🧠 tracemalloc         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│                               VS                                │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  METHOD B: STAC + DataCube Processing                     │  │
│  │                                                           │  │
│  │  Step B1: STAC Aggregation (rio-stac)                     │  │
│  │    1. Extract metadata, build ItemCollection              │  │
│  │    2. Output: stac_item_collection.json                   │  │
│  │  Step B2: NDWI Computation (pystac + rioxarray)           │  │
│  │    1. Load STAC JSON                                      │  │
│  │    2. Build 4D xarray DataCube from all images            │  │
│  │    3. Compute NDWI across full cube, export slices        │  │
│  │  Benchmark: ⏱ time.perf_counter + 🧠 tracemalloc         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                      │
│                          ▼                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  COMPARISON DASHBOARD                                     │  │
│  │  Head-to-head metrics: Method A vs Method B               │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 Setup Instructions

### Prerequisites

- **Python 3.9+** — [Download here](https://www.python.org/downloads/)
- **GDAL** — comes bundled with `rasterio` on most platforms. If you encounter issues on Windows, install via [OSGeo4W](https://trac.osgeo.org/osgeo4w/) or use pre-built wheels.

### Step-by-Step Installation

```powershell
# 1. Clone the repository and navigate to the directory
git clone https://github.com/Rohan-Ghadage-AIQ/NDWI-Pipeline.git
cd NDWI-Pipeline

# 2. Create a virtual environment
python -m venv venv

# 3. Activate the virtual environment
.\venv\Scripts\Activate.ps1

# 4. Install all dependencies
pip install -r requirements.txt
```

---

## 📦 Dependencies

| Package       | Purpose                                              |
|---------------|------------------------------------------------------|
| `numpy`       | Array math for NDWI computation                      |
| `pystac`      | Read/write STAC ItemCollections                      |
| `rasterio`    | Low-level raster I/O (GDAL bindings)                 |
| `rioxarray`   | Adds `.rio` accessor to xarray for CRS & GeoTIFF I/O |
| `stackstac`   | Converts STAC items → dask-backed xarray DataCube    |
| `rio-stac`    | Extracts geospatial metadata from rasters → STAC     |
| `xarray`      | N-dimensional labeled array framework                |
| `shapely`     | Geometry handling for STAC bounding boxes             |
| `dask[array]` | Lazy/chunked computation for large rasters           |

---

## 🚀 Usage

### Basic Run

```powershell
python ndwi_pipeline.py --input-dir .\sentinel2_images --output-dir .\output
```

### All CLI Options

| Flag             | Short | Default    | Description                                     |
|------------------|-------|------------|-------------------------------------------------|
| `--input-dir`    | `-i`  | *(required)* | Directory containing Sentinel-2 GeoTIFF files |
| `--output-dir`   | `-o`  | `./output` | Directory for all output files                  |
| `--green-band`   |       | `2`        | 0-indexed position of the Green band            |
| `--nir-band`     |       | `3`        | 0-indexed position of the NIR band              |

### Examples

```powershell
# Default band mapping (Green=index 2, NIR=index 3)
python ndwi_pipeline.py -i .\sentinel2_images -o .\output

# Custom band indices
python ndwi_pipeline.py -i .\data -o .\results --green-band 2 --nir-band 7

# Minimal — output goes to ./output by default
python ndwi_pipeline.py -i .\sentinel2_images
```

---

## 🧠 The "Why": STAC + DataCube vs. Individual Files

This pipeline deliberately compares two approaches. Why?

### Method A: Individual Files
The traditional approach. You open a GeoTIFF, read the bands, do the math, save the result, and move to the next file.
- **Pros:** Extremely memory efficient. Fast for small local batches.
- **Cons:** Hard to scale across distributed cloud clusters. Cannot easily do time-series math (like finding the "max NDWI over a year").

### Method B: STAC + DataCube (Cloud-Native)
The modern "Cloud-Native Geospatial" approach.
1. **STAC (SpatioTemporal Asset Catalog)** acts as an index/menu, allowing software to query metadata without downloading massive files.
2. **DataCube (xarray)** reads the STAC menu and stacks all images perfectly by coordinates into a single 4D array (`Time, Band, Y, X`).
- **Pros:** Allows you to perform complex mathematical formulas across billions of pixels simultaneously in a highly standardized way. Essential for scaling on cloud clusters (AWS/GCP).
- **Cons:** Requires immense RAM if forced to run locally without lazy-loading (as demonstrated in the benchmark below).

---

## 📊 Benchmark Dashboard

After execution, a formatted summary is printed to the console. Here are **actual results** comparing both methods on 12 Sentinel-2 images (2113×4198 pixels, 4 bands each):

```
══════════════════════════════════════════════════════════════════════
  PERFORMANCE COMPARISON DASHBOARD
══════════════════════════════════════════════════════════════════════
  Total GeoTIFF Images Processed  : 12
──────────────────────────────────────────────────────────────────────
  METHOD A — Individual File Processing (Baseline)
    NDWI files exported           : 12
    Wall Time (Execution)         : 15.713 s
    CPU Time (Compute Power)      : 0.000 s
    Peak Memory Usage             : 406.10 MB
──────────────────────────────────────────────────────────────────────
  METHOD B — STAC + DataCube Processing
    B1: STAC Aggregation Wall Time: 0.072 s
    B2: DataCube NDWI Wall Time   : 18.895 s
    Combined Wall Time (B1 + B2)  : 18.966 s
    Combined CPU Time  (B1 + B2)  : 11.500 s
    Peak Memory (max of B1, B2)   : 4873.57 MB
    NDWI files exported           : 12
──────────────────────────────────────────────────────────────────────
  METRIC                                   Method A      Method B
  ──────────────────────────────────── ────────────  ────────────
  Total Wall Time (s) [Lower=Faster]         15.713        18.966
  Total CPU Time (s)  [Compute Load]          0.000        11.500
  Peak Memory (MB)    [Lower=Lighter]        406.10       4873.57
──────────────────────────────────────────────────────────────────────

  📊 ANALYSIS & CONCLUSION:
  ────────────────────────────────────────────────────────────
  ⏱  Method A is 20.7% FASTER (Wall Time) than Method B
  ⚡ Method A requires vastly LESS CPU Compute Power than Method B
  🧠 Method B uses 1100.1% MORE memory than Method A

  💡 CONCLUSION:
     Method A (Individual) is FASTER and uses LESS memory.
     The STAC/DataCube overhead is not justified for this
     dataset size (12 images).
     However, Method B provides a standardized STAC catalog
     and scales better for cloud-native workflows.
```

### How Benchmarking Works

| Metric            | Tool                    | What It Measures                                        |
|-------------------|-------------------------|---------------------------------------------------------|
| **Execution Time** | `time.perf_counter()`  | Wall-clock elapsed time (high-resolution, includes I/O) |
| **CPU Time**       | `time.process_time()`  | Raw compute power (CPU load) used by the Python process |
| **Peak Memory**    | `tracemalloc`          | Peak memory allocated by the Python heap during the step |

Each step is measured **independently** — `tracemalloc` is started and stopped within each function so measurements don't bleed across steps.

### Key Insights from Comparison

- **CPU Compute Power**: Method A pushes all computation to highly optimized C-level C/C++ libraries inside `rasterio`/GDAL, leaving the Python CPU load at ~0 seconds. Method B uses `numpy` and `xarray` to process a massive 4D datacube in memory, which requires **11.5 seconds of heavy CPU lifting**.
- **Execution (Wall) Time**: Method A is actually ~3 seconds faster because it avoids the overhead of building a 4.8 GB array in memory.
- **Memory Consumption**: **Method B uses vastly more RAM** (~4.8 GB vs ~400 MB). This is because Method B loads the entire multi-temporal dataset into memory at once.
- **Conclusion**: For local processing of small-to-medium datasets, the individual `rasterio` loop (Method A) is highly memory-efficient, uses far less compute power, and is faster. The `xarray` DataCube (Method B) approach is better suited for distributed computing environments (like Dask clusters) where data is loaded lazily or in chunks across multiple nodes.

---

## 🔬 NDWI Formula

The **Normalized Difference Water Index** highlights water bodies in satellite imagery:

```
NDWI = (Green - NIR) / (Green + NIR)
```

| Value Range | Interpretation               |
|-------------|------------------------------|
| `+0.3 to +1.0` | Water bodies             |
| `0.0 to +0.3`  | Flooding, moisture       |
| `-0.3 to 0.0`  | Moderate drought         |
| `-1.0 to -0.3` | Dry land, vegetation     |

---

## ⚙️ Configuration

Band indices are defined at the top of [`ndwi_pipeline.py`](ndwi_pipeline.py):

```python
GREEN_BAND_INDEX: int = 2   # 0-indexed → Band 3 (Green)
NIR_BAND_INDEX: int   = 3   # 0-indexed → Band 8 (NIR)
```

You can change these directly in the file **or** override them at runtime via CLI flags.

---

## 🛡️ Error Handling

- If a single GeoTIFF fails to load in **Step 1**, the error is logged and the file is skipped — the rest of the batch continues.
- If a single time-slice fails to export in **Step 2**, the error is logged and the remaining slices are still exported.
- All errors are collected and displayed in the final benchmark dashboard.

---

## 🔄 Detailed Workflow

Here is the complete step-by-step data flow:

```
┌─────────────────────────────────────────────────────────────┐
│                     YOU (User)                              │
│  Place Sentinel-2 .tif files in a directory                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  python ndwi_pipeline.py --input-dir ./images -o ./output   │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
┌─────────────────────┐   ┌────────────────────────────────┐
│  METHOD A           │   │  METHOD B                      │
│  Individual Files   │   │  STAC + DataCube               │
├─────────────────────┤   ├────────────────────────────────┤
│ For each file:      │   │ 1. Scan directory              │
│  1. rasterio.open   │   │ 2. Create STAC ItemCollection  │
│  2. Read G, NIR     │   │ 3. Save stac.json              │
│  3. Calc NDWI       │   │ 4. Load stac.json              │
│  4. Save TIFF       │   │ 5. rioxarray load all images   │
└─────────┬───────────┘   │ 6. Concat to xarray DataCube   │
          │               │ 7. Calc NDWI vectorially       │
          │               │ 8. Export slices               │
          │               └───────────────┬────────────────┘
          │                               │
          └────────────┬──────────────────┘
                       ▼
          ┌─────────────────────────┐
          │  COMPARISON DASHBOARD   │
          │  • Execution Time       │
          │  • Peak Memory          │
          │  • Analysis             │
          └─────────────────────────┘
```

---

## 🔧 Troubleshooting

Common issues and their solutions:

### 1. PROJ Database Conflict (PostGIS / PostgreSQL)

```
PROJ: proj_create_from_database: ... contains DATABASE.LAYOUT.VERSION.MINOR = 2
whereas a number >= 6 is expected. It comes from another PROJ installation.
```

**Cause**: PostgreSQL/PostGIS installs an older PROJ database that rasterio picks up.
**Fix**: The script auto-detects and sets `PROJ_LIB` to rasterio's bundled `proj_data/` directory. No action needed — it's handled internally.

### 2. Unicode Encoding Error on Windows

```
UnicodeEncodeError: 'charmap' codec can't encode characters
```

**Cause**: PowerShell defaults to `cp1252` which can't render Unicode box-drawing characters.
**Fix**: The script calls `sys.stdout.reconfigure(encoding="utf-8")` at startup. Already handled.

### 3. stackstac Multi-Band Limitation

`stackstac` is designed for STAC catalogs where each band is a **separate COG asset**. Local Sentinel-2 files are **multi-band** GeoTIFFs (4 bands in one file). The script uses `rioxarray.open_rasterio()` instead, which correctly handles multi-band files.

### 4. "Error in sys.excepthook" on Exit

These harmless messages appear from dask/distributed thread cleanup when Python exits. They do **not** affect results or output files. You can safely ignore them.
