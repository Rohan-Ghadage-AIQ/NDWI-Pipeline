#!/usr/bin/env python3
"""
Sentinel-2 NDWI Pipeline — Computational Efficiency Comparison
================================================================

This script compares **two approaches** for computing the Normalized
Difference Water Index (NDWI) from Sentinel-2 multi-band GeoTIFFs:

  METHOD A — Individual File Processing (Baseline)
    Open each GeoTIFF directly with rasterio, extract Green & NIR bands,
    compute NDWI, and save.  Each file is processed independently.

  METHOD B — STAC-Aggregated DataCube Processing
    Step B1: Aggregate all GeoTIFFs into a STAC ItemCollection JSON
             using rio-stac.
    Step B2: Load the STAC catalog with pystac, build an xarray DataCube
             via rioxarray, compute NDWI across the full time-series,
             and export each time-slice.

Both methods are independently wrapped with ``time.perf_counter`` and
``tracemalloc`` so you can benchmark and compare them.

The final dashboard prints a side-by-side comparison so you can conclude
which approach is more efficient for your data size.

Usage
-----
    python ndwi_pipeline.py --input-dir ./sentinel2_images --output-dir ./output

Author : AI-generated — reviewed for production use
License: MIT
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Force UTF-8 output on Windows (PowerShell defaults to cp1252 which
# cannot render the Unicode box-drawing characters used in our dashboard).
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import time
import tracemalloc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List

def _fix_proj_data() -> None:
    """Point PROJ to rasterio's bundled proj_data to avoid version conflicts."""
    import importlib.util

    spec = importlib.util.find_spec("rasterio")
    if spec and spec.origin:
        rasterio_proj = Path(spec.origin).parent / "proj_data"
        if rasterio_proj.is_dir():
            os.environ["PROJ_LIB"]  = str(rasterio_proj)
            os.environ["PROJ_DATA"] = str(rasterio_proj)
            return

    try:
        import pyproj
        os.environ["PROJ_LIB"] = pyproj.datadir.get_data_dir()
    except Exception:
        pass

_fix_proj_data()

# ---------------------------------------------------------------------------
# Third-party imports
# ---------------------------------------------------------------------------
try:
    import numpy as np
    import pystac
    import rasterio
    import rioxarray          # noqa: F401 – needed for .rio accessor on xarray
    import xarray as xr
    from rio_stac import create_stac_item
except ImportError as exc:
    sys.exit(
        f"Missing required dependency: {exc.name}\n"
        "Install all requirements with:\n"
        "  pip install numpy pystac rasterio rioxarray rio-stac xarray pyproj"
    )

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION — edit these if your band layout differs
# ═══════════════════════════════════════════════════════════════════════════
GREEN_BAND_INDEX: int = 2   # 0-indexed position of Band 3 (Green)
NIR_BAND_INDEX: int   = 3   # 0-indexed position of Band 8 (NIR)

STAC_COLLECTION_ID: str = "sentinel2-local"
STAC_OUTPUT_FILENAME: str = "stac_item_collection.json"

# Supported raster extensions
TIFF_EXTENSIONS: tuple[str, ...] = ("*.tif", "*.tiff", "*.TIF", "*.TIFF")


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════
@dataclass
class BenchmarkResult:
    """Container for a single step's benchmark metrics."""
    step_name: str
    elapsed_seconds: float = 0.0
    cpu_seconds: float = 0.0
    peak_memory_mb: float = 0.0
    items_processed: int = 0
    errors: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# HELPER — discover GeoTIFF files
# ═══════════════════════════════════════════════════════════════════════════
def discover_tiff_files(directory: str | Path) -> List[Path]:
    """Return a sorted list of GeoTIFF file paths found in *directory*."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {directory}")

    found: set[Path] = set()
    for ext in TIFF_EXTENSIONS:
        found.update(directory.glob(ext))

    return sorted(found)


# ═══════════════════════════════════════════════════════════════════════════
# METHOD A — INDIVIDUAL FILE NDWI (BASELINE)
# ═══════════════════════════════════════════════════════════════════════════
def method_a_individual_ndwi(
    input_dir: str | Path,
    output_dir: str | Path,
) -> BenchmarkResult:
    """Compute NDWI for each GeoTIFF file independently using rasterio.

    This is the **baseline** approach: open each file one at a time,
    read the Green and NIR bands, compute NDWI, and write the result
    to a separate output GeoTIFF.  No STAC catalog or DataCube is used.

    This represents how a typical geospatial analyst would process files
    in a simple loop without any catalog or array framework overhead.

    Benchmarking
    -------------
    * ``tracemalloc`` captures peak Python heap memory.
    * ``time.perf_counter`` provides wall-clock elapsed time.
    """
    bench = BenchmarkResult(step_name="Method A: Individual File NDWI")
    output_dir = Path(output_dir)
    ndwi_dir = output_dir / "ndwi_individual"
    ndwi_dir.mkdir(parents=True, exist_ok=True)

    tiff_files = discover_tiff_files(input_dir)
    if not tiff_files:
        raise RuntimeError(f"No GeoTIFF files found in {input_dir}")

    print(f"\n{'═'*62}")
    print(f"  METHOD A ▸ Individual File NDWI (Baseline)")
    print(f"  Found {len(tiff_files)} GeoTIFF file(s) in {input_dir}")
    print(f"{'═'*62}")

    # ------------------------------------------------------------------
    # Start benchmarking
    # ------------------------------------------------------------------
    tracemalloc.start()
    t_start = time.perf_counter()
    cpu_start = time.process_time()

    exported_count = 0

    for idx, tiff_path in enumerate(tiff_files, start=1):
        try:
            print(f"  [{idx}/{len(tiff_files)}] {tiff_path.name}", end=" → ")

            # Open the multi-band GeoTIFF with rasterio
            with rasterio.open(str(tiff_path)) as src:
                # Read the Green and NIR bands (1-indexed in rasterio)
                green = src.read(GREEN_BAND_INDEX + 1).astype(np.float64)
                nir   = src.read(NIR_BAND_INDEX + 1).astype(np.float64)

                # Compute NDWI = (Green - NIR) / (Green + NIR)
                epsilon = 1e-10
                ndwi = (green - nir) / (green + nir + epsilon)

                # Write the NDWI result as a single-band GeoTIFF
                out_path = ndwi_dir / f"ndwi_{tiff_path.stem}.tif"
                profile = src.profile.copy()
                profile.update(
                    count=1,
                    dtype="float64",
                    driver="GTiff",
                )

                with rasterio.open(str(out_path), "w", **profile) as dst:
                    dst.write(ndwi, 1)

            print(f"✓ {out_path.name}")
            exported_count += 1

        except Exception as exc:
            msg = f"⚠  Failed {tiff_path.name}: {exc}"
            print(msg)
            bench.errors.append(msg)

    # ------------------------------------------------------------------
    # Stop benchmarking
    # ------------------------------------------------------------------
    t_end = time.perf_counter()
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    bench.elapsed_seconds = t_end - t_start
    bench.peak_memory_mb = peak_bytes / (1024 * 1024)
    bench.items_processed = exported_count

    print(f"  {'─'*56}")
    print(f"  ✓ {exported_count} NDWI file(s) → {ndwi_dir}")
    print(f"  ⏱ {bench.elapsed_seconds:.3f}s  |  "
          f"🧠 {bench.peak_memory_mb:.2f} MB peak RAM")

    return bench


# ═══════════════════════════════════════════════════════════════════════════
# METHOD B, STEP 1 — STAC CATALOG CREATION
# ═══════════════════════════════════════════════════════════════════════════
def method_b_step1_create_stac(
    input_dir: str | Path,
    output_dir: str | Path,
) -> tuple[Path, BenchmarkResult]:
    """Scan input directory for GeoTIFFs and build a STAC ItemCollection.

    This is the metadata-aggregation overhead of the STAC-based approach.
    It does NOT compute NDWI — that happens in Step 2.
    """
    bench = BenchmarkResult(step_name="Method B / Step 1: STAC Aggregation")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tiff_files = discover_tiff_files(input_dir)
    if not tiff_files:
        raise RuntimeError(f"No GeoTIFF files found in {input_dir}")

    print(f"\n{'═'*62}")
    print(f"  METHOD B / STEP 1 ▸ STAC Catalog Creation")
    print(f"  Found {len(tiff_files)} GeoTIFF file(s) in {input_dir}")
    print(f"{'═'*62}")

    # ------------------------------------------------------------------
    # Start benchmarking
    # ------------------------------------------------------------------
    tracemalloc.start()
    t_start = time.perf_counter()
    cpu_start = time.process_time()

    items: list[pystac.Item] = []

    for idx, tiff_path in enumerate(tiff_files, start=1):
        try:
            print(f"  [{idx}/{len(tiff_files)}] Cataloging: {tiff_path.name}")

            item: pystac.Item = create_stac_item(
                source=str(tiff_path),
                collection=STAC_COLLECTION_ID,
                asset_name="image",
                asset_media_type=pystac.MediaType.GEOTIFF,
                with_proj=True,
            )

            item.id = tiff_path.stem

            if item.datetime is None:
                mtime = os.path.getmtime(tiff_path)
                item.datetime = datetime.fromtimestamp(mtime, tz=timezone.utc)

            for asset in item.assets.values():
                asset.href = str(tiff_path.resolve())

            # Ensure proj:epsg is set (PROJ conflict may prevent auto-detect)
            if not item.properties.get("proj:epsg"):
                with rasterio.open(str(tiff_path)) as src:
                    epsg_code = src.crs.to_epsg() if src.crs else None
                    item.properties["proj:epsg"] = epsg_code or 4326

            items.append(item)

        except Exception as exc:
            msg = f"⚠  Skipped {tiff_path.name}: {exc}"
            print(f"  {msg}")
            bench.errors.append(msg)

    # Write the ItemCollection JSON
    item_collection = pystac.ItemCollection(items=items)
    stac_path = output_dir / STAC_OUTPUT_FILENAME

    with open(stac_path, "w", encoding="utf-8") as fp:
        json.dump(item_collection.to_dict(), fp, indent=2, default=str)

    # ------------------------------------------------------------------
    # Stop benchmarking
    # ------------------------------------------------------------------
    cpu_end = time.process_time()
    t_end = time.perf_counter()
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    bench.elapsed_seconds = t_end - t_start
    bench.cpu_seconds = cpu_end - cpu_start
    bench.peak_memory_mb = peak_bytes / (1024 * 1024)
    bench.items_processed = len(items)

    print(f"  {'─'*56}")
    print(f"  ✓ STAC catalog → {stac_path}")
    print(f"  ⏱ {bench.elapsed_seconds:.3f}s (Wall) | "
          f"⚡ {bench.cpu_seconds:.3f}s (CPU) | "
          f"🧠 {bench.peak_memory_mb:.2f} MB peak RAM")

    return stac_path, bench


# ═══════════════════════════════════════════════════════════════════════════
# METHOD B, STEP 2 — DATACUBE NDWI VIA STAC
# ═══════════════════════════════════════════════════════════════════════════
def method_b_step2_datacube_ndwi(
    stac_json_path: str | Path,
    output_dir: str | Path,
) -> BenchmarkResult:
    """Load a STAC ItemCollection, build an xarray DataCube, compute NDWI
    across the entire time-series, and export each time-slice.

    This represents the DataCube-based approach where all images are
    loaded into a unified (time, band, y, x) array and band math is
    applied vectorially across the whole cube at once.
    """
    bench = BenchmarkResult(step_name="Method B / Step 2: DataCube NDWI")
    output_dir = Path(output_dir)
    ndwi_dir = output_dir / "ndwi_datacube"
    ndwi_dir.mkdir(parents=True, exist_ok=True)

    stac_json_path = Path(stac_json_path)
    if not stac_json_path.is_file():
        raise FileNotFoundError(f"STAC JSON not found: {stac_json_path}")

    print(f"\n{'═'*62}")
    print(f"  METHOD B / STEP 2 ▸ DataCube NDWI via STAC")
    print(f"{'═'*62}")

    # ------------------------------------------------------------------
    # Start benchmarking
    # ------------------------------------------------------------------
    tracemalloc.start()
    t_start = time.perf_counter()
    cpu_start = time.process_time()

    # Load STAC ItemCollection
    with open(stac_json_path, "r", encoding="utf-8") as fp:
        stac_dict = json.load(fp)

    item_collection = pystac.ItemCollection.from_dict(stac_dict)
    stac_items = list(item_collection.items)
    n_items = len(stac_items)
    print(f"  Loaded {n_items} STAC item(s)")

    if n_items == 0:
        raise RuntimeError("The STAC ItemCollection contains zero items.")

    # Build the xarray DataCube from multi-band GeoTIFFs
    print("  Building xarray DataCube via rioxarray …")

    time_slices: list[xr.DataArray] = []
    timestamps: list[str] = []
    item_ids: list[str] = []

    for item in stac_items:
        asset_href = list(item.assets.values())[0].href

        try:
            da = rioxarray.open_rasterio(asset_href)
            time_slices.append(da)
            ts = item.datetime.isoformat() if item.datetime else item.id
            timestamps.append(ts)
            item_ids.append(item.id)
        except Exception as exc:
            msg = f"⚠  Failed to load {item.id}: {exc}"
            print(f"  {msg}")
            bench.errors.append(msg)

    if not time_slices:
        raise RuntimeError("No images could be loaded from the STAC catalog.")

    # Concatenate into DataCube: (time, band, y, x)
    data_cube: xr.DataArray = xr.concat(
        time_slices,
        dim=xr.Variable("time", timestamps),
    )
    print(f"  DataCube shape: {dict(data_cube.sizes)}")

    # Extract Green and NIR bands (0-indexed positional selection)
    green: xr.DataArray = data_cube.isel(band=GREEN_BAND_INDEX)
    nir: xr.DataArray   = data_cube.isel(band=NIR_BAND_INDEX)

    print(f"  Green (index {GREEN_BAND_INDEX}) and "
          f"NIR (index {NIR_BAND_INDEX}) extracted")

    # Compute NDWI across the entire cube at once
    green_f = green.astype(np.float64)
    nir_f   = nir.astype(np.float64)
    epsilon = 1e-10
    ndwi: xr.DataArray = (green_f - nir_f) / (green_f + nir_f + epsilon)

    print(f"  NDWI cube shape: {dict(ndwi.sizes)}")

    # Export each time-slice as a GeoTIFF
    exported_count = 0
    n_time = ndwi.sizes.get("time", 1)

    for t_idx in range(n_time):
        try:
            if "time" in ndwi.dims:
                slice_da: xr.DataArray = ndwi.isel(time=t_idx)
            else:
                slice_da = ndwi

            # Clean inherited multi-band attributes
            for attr_name in ("long_name", "standard_name"):
                if attr_name in slice_da.attrs:
                    del slice_da.attrs[attr_name]
            slice_da.attrs["long_name"] = "NDWI"

            out_path = ndwi_dir / f"ndwi_{item_ids[t_idx]}.tif"

            # Ensure CRS is attached
            if slice_da.rio.crs is None:
                src_crs = time_slices[0].rio.crs
                if src_crs:
                    slice_da = slice_da.rio.write_crs(src_crs)

            if "band" not in slice_da.dims:
                slice_da = slice_da.expand_dims("band")

            slice_da.rio.to_raster(str(out_path), driver="GTiff")
            print(f"  [{t_idx + 1}/{n_time}] Saved: {out_path.name}")
            exported_count += 1

        except Exception as exc:
            msg = f"⚠  Failed to export time-slice {t_idx}: {exc}"
            print(f"  {msg}")
            bench.errors.append(msg)

    # ------------------------------------------------------------------
    # Stop benchmarking
    # ------------------------------------------------------------------
    cpu_end = time.process_time()
    t_end = time.perf_counter()
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    bench.elapsed_seconds = t_end - t_start
    bench.cpu_seconds = cpu_end - cpu_start
    bench.peak_memory_mb = peak_bytes / (1024 * 1024)
    bench.items_processed = exported_count

    print(f"  {'─'*56}")
    print(f"  ✓ {exported_count} NDWI file(s) → {ndwi_dir}")
    print(f"  ⏱ {bench.elapsed_seconds:.3f}s (Wall) | "
          f"⚡ {bench.cpu_seconds:.3f}s (CPU) | "
          f"🧠 {bench.peak_memory_mb:.2f} MB peak RAM")

    return bench


# ═══════════════════════════════════════════════════════════════════════════
# COMPARISON DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════
def print_comparison_dashboard(
    total_images: int,
    bench_a: BenchmarkResult,
    bench_b1: BenchmarkResult,
    bench_b2: BenchmarkResult,
) -> None:
    """Print a side-by-side comparison of Method A vs Method B."""

    width = 70
    hr = "═" * width

    # Method B combined metrics
    b_total_time = bench_b1.elapsed_seconds + bench_b2.elapsed_seconds
    b_total_cpu  = bench_b1.cpu_seconds + bench_b2.cpu_seconds
    b_peak_mem   = max(bench_b1.peak_memory_mb, bench_b2.peak_memory_mb)
    all_errors   = bench_a.errors + bench_b1.errors + bench_b2.errors

    print(f"\n{hr}")
    print("  PERFORMANCE COMPARISON DASHBOARD")
    print(hr)
    print(f"  Total GeoTIFF Images Processed  : {total_images}")
    print(f"{'─'*width}")

    # --- Method A summary ---
    print(f"  METHOD A — Individual File Processing (Baseline)")
    print(f"    NDWI files exported           : {bench_a.items_processed}")
    print(f"    Wall Time (Execution)         : {bench_a.elapsed_seconds:.3f} s")
    print(f"    CPU Time (Compute Power)      : {bench_a.cpu_seconds:.3f} s")
    print(f"    Peak Memory Usage             : {bench_a.peak_memory_mb:.2f} MB")
    print(f"{'─'*width}")

    # --- Method B summary ---
    print(f"  METHOD B — STAC + DataCube Processing")
    print(f"    B1: STAC Aggregation Wall Time: {bench_b1.elapsed_seconds:.3f} s")
    print(f"    B2: DataCube NDWI Wall Time   : {bench_b2.elapsed_seconds:.3f} s")
    print(f"    Combined Wall Time (B1 + B2)  : {b_total_time:.3f} s")
    print(f"    Combined CPU Time  (B1 + B2)  : {b_total_cpu:.3f} s")
    print(f"    Peak Memory (max of B1, B2)   : {b_peak_mem:.2f} MB")
    print(f"    NDWI files exported           : {bench_b2.items_processed}")
    print(f"{'─'*width}")

    # --- Head-to-head comparison ---
    print(f"  {'METRIC':<36} {'Method A':>12}  {'Method B':>12}")
    print(f"  {'─'*36} {'─'*12}  {'─'*12}")
    print(f"  {'Total Wall Time (s) [Lower=Faster]':<36} "
          f"{bench_a.elapsed_seconds:>12.3f}  "
          f"{b_total_time:>12.3f}")
    print(f"  {'Total CPU Time (s)  [Compute Load]':<36} "
          f"{bench_a.cpu_seconds:>12.3f}  "
          f"{b_total_cpu:>12.3f}")
    print(f"  {'Peak Memory (MB)    [Lower=Lighter]':<36} "
          f"{bench_a.peak_memory_mb:>12.2f}  "
          f"{b_peak_mem:>12.2f}")
    print(f"{'─'*width}")

    # --- Verdict ---
    wall_ratio = b_total_time / bench_a.elapsed_seconds if bench_a.elapsed_seconds > 0 else float('inf')
    cpu_ratio  = b_total_cpu / bench_a.cpu_seconds if bench_a.cpu_seconds > 0 else float('inf')
    mem_ratio  = b_peak_mem / bench_a.peak_memory_mb if bench_a.peak_memory_mb > 0 else float('inf')

    print(f"\n  📊 ANALYSIS & CONCLUSION:")
    print(f"  {'─'*60}")

    # Wall Time comparison
    if b_total_time < bench_a.elapsed_seconds:
        time_pct = (1 - wall_ratio) * 100
        print(f"  ⏱  Method B is {time_pct:.1f}% FASTER (Wall Time) than Method A")
    elif b_total_time > bench_a.elapsed_seconds:
        time_pct = (wall_ratio - 1) * 100
        print(f"  ⏱  Method A is {time_pct:.1f}% FASTER (Wall Time) than Method B")
    else:
        print(f"  ⏱  Both methods have equal wall execution time")

    # CPU Time comparison
    if b_total_cpu < bench_a.cpu_seconds:
        cpu_pct = (1 - cpu_ratio) * 100
        print(f"  ⚡ Method B requires {cpu_pct:.1f}% LESS CPU Compute Power than Method A")
    elif b_total_cpu > bench_a.cpu_seconds:
        cpu_pct = (cpu_ratio - 1) * 100
        print(f"  ⚡ Method A requires {cpu_pct:.1f}% LESS CPU Compute Power than Method B")
    else:
        print(f"  ⚡ Both methods use equal CPU compute power")

    # Memory comparison
    if b_peak_mem < bench_a.peak_memory_mb:
        mem_pct = (1 - mem_ratio) * 100
        print(f"  🧠 Method B uses {mem_pct:.1f}% LESS memory than Method A")
    elif b_peak_mem > bench_a.peak_memory_mb:
        mem_pct = (mem_ratio - 1) * 100
        print(f"  🧠 Method B uses {mem_pct:.1f}% MORE memory than Method A")
    else:
        print(f"  🧠 Both methods have equal memory usage")

    # Overall conclusion
    print(f"\n  💡 CONCLUSION:")
    if bench_a.elapsed_seconds < b_total_time and bench_a.peak_memory_mb < b_peak_mem:
        print(f"     Method A (Individual) is FASTER and uses LESS memory.")
        print(f"     The STAC/DataCube overhead is not justified for this")
        print(f"     dataset size ({total_images} images).")
        print(f"     However, Method B provides a standardized STAC catalog")
        print(f"     and scales better for cloud-native workflows.")
    elif bench_a.elapsed_seconds > b_total_time and bench_a.peak_memory_mb > b_peak_mem:
        print(f"     Method B (STAC/DataCube) is FASTER and uses LESS memory.")
        print(f"     The DataCube approach provides both better performance")
        print(f"     and a standardized STAC catalog for reproducibility.")
    elif bench_a.elapsed_seconds < b_total_time:
        print(f"     Method A is FASTER but uses LESS memory.")
        print(f"     Method B trades speed for a unified DataCube that enables")
        print(f"     vectorized operations and a STAC catalog for metadata.")
        print(f"     The DataCube loads ALL images into RAM at once ({b_peak_mem:.0f} MB),")
        print(f"     while Method A processes one file at a time ({bench_a.peak_memory_mb:.0f} MB).")
    else:
        print(f"     Method B is FASTER but uses MORE memory.")
        print(f"     The DataCube approach benefits from vectorized numpy")
        print(f"     operations at the cost of higher RAM consumption.")

    # Error summary
    total_errors = len(all_errors)
    print(f"\n  Total Errors / Warnings         : {total_errors}")
    if all_errors:
        print(f"\n  ⚠  Error Details:")
        for err in all_errors:
            print(f"     • {err}")

    print(f"\n{hr}")


# ═══════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════
def parse_args() -> argparse.Namespace:
    """Define and parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Sentinel-2 NDWI Pipeline — Compare individual file processing "
            "vs STAC/DataCube processing and benchmark both approaches."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input-dir", "-i",
        type=str,
        required=True,
        help="Path to the directory containing Sentinel-2 GeoTIFF files.",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="./output",
        help="Path to the output directory (default: ./output).",
    )
    parser.add_argument(
        "--green-band", type=int, default=None,
        help=f"Override 0-indexed Green band position (default: {GREEN_BAND_INDEX}).",
    )
    parser.add_argument(
        "--nir-band", type=int, default=None,
        help=f"Override 0-indexed NIR band position (default: {NIR_BAND_INDEX}).",
    )
    return parser.parse_args()


def main() -> None:
    """Orchestrate both methods and print the comparison dashboard."""

    args = parse_args()

    # Allow CLI overrides for band indices
    global GREEN_BAND_INDEX, NIR_BAND_INDEX
    if args.green_band is not None:
        GREEN_BAND_INDEX = args.green_band
    if args.nir_band is not None:
        NIR_BAND_INDEX = args.nir_band

    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║  Sentinel-2 NDWI Pipeline — Computational Efficiency Comparison    ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print(f"║  Input Dir  : {str(args.input_dir):<54}║")
    print(f"║  Output Dir : {str(args.output_dir):<54}║")
    print(f"║  Green Band : index {GREEN_BAND_INDEX:<48}║")
    print(f"║  NIR Band   : index {NIR_BAND_INDEX:<48}║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print("║  Method A : Individual file NDWI (rasterio)  — Baseline           ║")
    print("║  Method B : STAC aggregation → DataCube NDWI (pystac + xarray)    ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    total_images = len(discover_tiff_files(args.input_dir))

    # ── METHOD A — Individual File Processing ─────────────────────────
    bench_a = method_a_individual_ndwi(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
    )

    # ── METHOD B — STAC + DataCube ────────────────────────────────────
    # Step B1: Create STAC catalog
    stac_path, bench_b1 = method_b_step1_create_stac(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
    )

    # Step B2: DataCube NDWI from STAC
    bench_b2 = method_b_step2_datacube_ndwi(
        stac_json_path=stac_path,
        output_dir=args.output_dir,
    )

    # ── Comparison Dashboard ──────────────────────────────────────────
    print_comparison_dashboard(total_images, bench_a, bench_b1, bench_b2)


if __name__ == "__main__":
    main()
