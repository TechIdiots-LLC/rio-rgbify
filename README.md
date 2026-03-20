# rio-rgbify
Encode arbitrary bit depth rasters in pseudo base-256 as RGB, outputting to **MBTiles** or **PMTiles** format.

## Installation

```
git clone --recurse-submodules https://github.com/acalcutt/rio-rgbify.git

cd rio-rgbify

pip install -e '.[test]'
```

> **Note:** The `--recurse-submodules` flag is required to initialise the bundled PMTiles library. If you already cloned without it, run:
> ```
> git submodule update --init --recursive
> ```

## Required Packages on Ubuntu
To run `rio-rgbify` on Ubuntu, you will need to make sure you have the following installed:

*   `python3-dev`
*   `libspatialindex-dev`
*   `libgeos-dev`
*   `gdal-bin`
*   `python3-gdal`

You can install these using the following command:

```bash
sudo apt update
sudo apt install python3-dev libspatialindex-dev libgeos-dev gdal-bin python3-gdal
```

## CLI usage

`rio-rgbify` has two subcommands: `rgbify` and `merge`.

---

### `rgbify` Command

Encodes a source raster into RGB tiles and writes them to an **MBTiles** or **PMTiles** file.

- Input can be any raster readable by `rasterio`
- Output format is determined automatically from the file extension (`.pmtiles` → PMTiles, anything else → MBTiles), or can be forced with `--output-format`

```
Usage: rio rgbify [OPTIONS] SRC_PATH DST_PATH

  rio-rgbify cli.

Options:
  -b, --base-val FLOAT            The base value of which to base the output
                                  encoding on [DEFAULT=0]
  -i, --interval FLOAT            Describes the precision of the output, by
                                  incrementing interval [DEFAULT=1]
  -r, --round-digits INTEGER      Less significant encoded bits to be set to
                                  0. Rounds values but improves image
                                  compression [DEFAULT=0]
  -e, --encoding [mapbox|terrarium]
                                  RGB encoding to use on the tiles
  --bidx INTEGER                  Band to encode [DEFAULT=1]
  --max-z INTEGER                 Maximum zoom level to tile
  --bounding-tile TEXT            Bounding tile '[x, y, z]' to limit output
  --min-z INTEGER                 Minimum zoom level to tile
  --format [png|webp]             Output tile image format [DEFAULT=png]
  --output-format [mbtiles|pmtiles]
                                  Output archive format. Defaults to auto-
                                  detect from DST_PATH extension.
  -j, --workers INTEGER           Workers to run [DEFAULT=4]
  --batch-size INTEGER            Number of tiles per batch per process
  --resampling [nearest|bilinear|cubic|cubic_spline|lanczos|average|mode|gauss]
                                  Resampling method [DEFAULT=nearest]
  -v, --verbose
  -h, --help                      Show this message and exit.
```

#### Mapbox TerrainRGB — MBTiles output

```bash
rio rgbify -e mapbox -b -10000 -i 0.1 --min-z 0 --max-z 8 -j 24 --format png SRC_PATH.vrt output.mbtiles
```

#### Mapbox TerrainRGB — PMTiles output

```bash
rio rgbify -e mapbox -b -10000 -i 0.1 --min-z 0 --max-z 8 -j 24 --format png SRC_PATH.vrt output.pmtiles
```

#### Mapzen Terrarium — MBTiles output

```bash
rio rgbify -e terrarium --min-z 0 --max-z 8 -j 24 --format png SRC_PATH.vrt output.mbtiles
```

---

### `merge` Command

Merges multiple **MBTiles**, **PMTiles**, or **raster** sources into a single output file. Sources are layered in priority order — the first source takes precedence, and later sources fill gaps.

The output file can be **MBTiles** or **PMTiles**. When the output path ends in `.pmtiles`, the merge is written to a temporary MBTiles scratch file (keeping parallel SQLite writes intact) then converted to PMTiles at the end — no large in-memory buffers are needed.

```
Usage: rio merge [OPTIONS]

Options:
  -c, --config PATH       Path to the JSON configuration file [required]
  -j, --workers INTEGER   Number of parallel worker processes
  -v, --verbose
  -h, --help              Show this message and exit.
```

#### Configuration File

The `merge` command reads a JSON configuration file passed via `--config`.

##### MBTiles / PMTiles sources → MBTiles output

```json
{
    "output_type": "mbtiles",
    "output_path": "/path/to/output.mbtiles",
    "output_encoding": "mapbox",
    "output_format": "webp",
    "output_nodata": -9999,
    "resampling": "bilinear",
    "sparse_tiles": true,
    "min_zoom": 2,
    "max_zoom": 10,
    "gaussian_blur_sigma": 0.2,
    "bounds": [-10, 10, 20, 50],
    "bounds_source": 1,
    "sources": [
        {
            "source_type": "mbtiles",
            "path": "/path/to/high_res.mbtiles",
            "encoding": "mapbox",
            "height_adjustment": 0.0,
            "base_val": -10000,
            "interval": 0.1,
            "mask_values": [-1, 0]
        },
        {
            "source_type": "pmtiles",
            "path": "/path/to/base_terrain.pmtiles",
            "encoding": "mapbox",
            "height_adjustment": 0.0,
            "base_val": -10000,
            "interval": 0.1,
            "mask_values": [0.0]
        },
        {
            "source_type": "mbtiles",
            "path": "/path/to/bathymetry.mbtiles",
            "encoding": "mapbox",
            "height_adjustment": -5.0
        }
    ]
}
```

##### MBTiles / PMTiles sources → PMTiles output

Set `"output_type": "pmtiles"` and use a `.pmtiles` output path. Everything else is identical to the MBTiles example above.

```json
{
    "output_type": "pmtiles",
    "output_path": "/path/to/output.pmtiles",
    "output_encoding": "mapbox",
    "output_format": "webp",
    "sources": [
        {
            "source_type": "pmtiles",
            "path": "/path/to/high_res.pmtiles",
            "encoding": "mapbox"
        },
        {
            "source_type": "mbtiles",
            "path": "/path/to/low_res.mbtiles",
            "encoding": "mapbox"
        }
    ],
    "min_zoom": 0,
    "max_zoom": 12
}
```

##### Raster sources → MBTiles output

```json
{
    "output_type": "raster",
    "output_path": "/path/to/output.mbtiles",
    "output_encoding": "terrarium",
    "output_format": "webp",
    "output_nodata": -9999,
    "resampling": "bilinear",
    "sparse_tiles": true,
    "min_zoom": 2,
    "max_zoom": 10,
    "bounds": [-10, 10, 20, 50],
    "bounds_source": 1,
    "sources": [
        {
            "source_type": "raster",
            "path": "/path/to/raster1.tif",
            "height_adjustment": -5.0,
            "base_val": -10000,
            "interval": 0.1,
            "mask_values": [0]
        },
        {
            "source_type": "raster",
            "path": "/path/to/raster2.tif",
            "height_adjustment": 10.0,
            "mask_values": [-1, -32767]
        }
    ]
}
```

#### Configuration Reference

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `output_type` | No | `"mbtiles"` | Output format: `"mbtiles"`, `"pmtiles"`, or `"raster"` |
| `output_path` | No | `"output.mbtiles"` | Path for the merged output file |
| `output_encoding` | No | `"mapbox"` | Output RGB encoding: `"mapbox"` or `"terrarium"` |
| `output_format` | No | `"png"` | Output tile image format: `"png"` or `"webp"` |
| `output_nodata` | No | `null` | If set, NaN elevation values are replaced with this number |
| `resampling` | No | `"bilinear"` | Resampling method: `"nearest"`, `"bilinear"`, `"cubic"`, `"cubic_spline"`, `"lanczos"`, `"average"`, `"mode"`, `"gauss"` |
| `sparse_tiles` | No | `false` | Skip tiles that contain only upscaled data |
| `min_zoom` | No | `0` | Minimum zoom level to process |
| `max_zoom` | No | max zoom of bounds source | Maximum zoom level to process |
| `bounds` | No | bounds of bounds source | Bounding box `[w, s, e, n]` to limit tile generation. Overrides `bounds_source`. |
| `bounds_source` | No | last source | Index (0-based) of the source whose tile list defines which tiles to process |
| `gaussian_blur_sigma` | No | `0.2` | Base sigma for Gaussian blur applied during upscaling (actual sigma = `gaussian_blur_sigma × zoom_diff`) |

**Per-source fields** (inside the `sources` array):

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `source_type` | No | `"mbtiles"` | Source type: `"mbtiles"`, `"pmtiles"`, or `"raster"` |
| `path` | Yes | — | Path to the source file |
| `encoding` | No | `"mapbox"` | RGB encoding of the source: `"mapbox"` or `"terrarium"` (MBTiles / PMTiles only) |
| `height_adjustment` | No | `0.0` | Metres to add/subtract from the elevation of this source |
| `base_val` | No | `-10000` | Base elevation value for decoding (mapbox default) |
| `interval` | No | `0.1` | Elevation interval used when decoding |
| `mask_values` | No | `[0.0]` | Elevation values to treat as nodata |

#### Understanding zoom-level dependent blurring

The `gaussian_blur_sigma` value is a *base* scalar. When a tile needs upscaling the actual sigma applied is:

```
actual_sigma = gaussian_blur_sigma × |target_zoom − source_zoom|
```

This means tiles requiring significant upscaling receive proportionally more smoothing (reducing blockiness), while tiles at or near their native zoom receive minimal smoothing. Start with the default (`0.2`) and increase it if upscaled tiles look blocky, or decrease it if they look too blurry.

The merge processes sources in order — the first source takes precedence and later sources fill gaps where the higher-priority sources have no data.

## Example commands

```bash
# Merge with MBTiles output
rio merge --config config.json -j 24

# Merge with PMTiles output (set output_type and output_path in config)
rio merge --config config_pmtiles.json -j 24
```

