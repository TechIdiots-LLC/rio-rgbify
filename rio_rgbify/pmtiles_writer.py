"""PMTiles output writer for rio-rgbify.

Uses the PMTiles submodule (PMTiles/python/pmtiles) to write tiles to the
PMTiles v3 archive format, mirroring the interface of MBTilesDatabase so that
RGBTiler can use either backend transparently.
"""
from __future__ import annotations

import datetime
import logging
import math
import os
import sys
import traceback
from typing import List, Optional

# ---------------------------------------------------------------------------
# Locate and load the PMTiles Python package from the submodule.
# Path layout: <repo root>/PMTiles/python/pmtiles/pmtiles/
# ---------------------------------------------------------------------------
_pmtiles_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "PMTiles", "python", "pmtiles")
)
if _pmtiles_path not in sys.path:
    sys.path.insert(0, _pmtiles_path)

try:
    from pmtiles.writer import Writer
    from pmtiles.tile import zxy_to_tileid, TileType, Compression
except ImportError as exc:
    raise ImportError(
        "Could not import the PMTiles Python library. "
        "Make sure the PMTiles submodule has been initialised:\n"
        "  git submodule update --init --recursive"
    ) from exc


def _tile_type_for_format(fmt: str) -> TileType:
    """Map an image format string to a PMTiles TileType."""
    return {
        "png": TileType.PNG,
        "webp": TileType.WEBP,
        "jpg": TileType.JPEG,
        "jpeg": TileType.JPEG,
    }.get(fmt.lower(), TileType.PNG)


class PMTilesWriter:
    """Context-manager that buffers RGB tiles and writes a PMTiles v3 archive.

    The public interface intentionally mirrors ``MBTilesDatabase`` so that
    ``RGBTiler`` can swap backends without branching everywhere.

    Usage::

        with PMTilesWriter("output.pmtiles") as writer:
            writer.add_bounds_center_metadata(bounds, min_z, max_z, encoding, fmt)
            writer.insert_tile_with_retry(tile, data, use_inverse_y=True)
            # commit() is a no-op but accepted for interface compatibility
            writer.commit()
        # The archive is finalised and flushed on __exit__.
    """

    def __init__(self, outpath: str):
        self.outpath = outpath
        # tile_id (int) → bytes; using a dict naturally deduplicates by position
        self._tiles: dict[int, bytes] = {}
        self._header: dict = {}
        self._metadata: dict = {}

    # ------------------------------------------------------------------
    # Context-manager protocol
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_t, exc_v, tb):
        if exc_t:
            traceback.print_exc()
        else:
            self._finalise()

    # ------------------------------------------------------------------
    # Public interface (mirrors MBTilesDatabase)
    # ------------------------------------------------------------------

    def commit(self):
        """No-op – accepts commits issued by RGBTiler for interface compatibility."""

    def add_bounds_center_metadata(
        self,
        bounds: Optional[List[float]],
        min_zoom: int,
        max_zoom: int,
        encoding: str,
        fmt: str,
        name: str = "Terrain",
    ):
        """Build the PMTiles header and metadata from raster bounds."""
        if bounds is None:
            w, s, e, n = -180.0, -90.0, 180.0, 90.0
        else:
            w, s, e, n = bounds

        center_lon = (w + e) / 2.0
        center_lat = (n + s) / 2.0
        center_zoom = (min_zoom + max_zoom) // 2

        tile_type = _tile_type_for_format(fmt)

        self._header = {
            "tile_type": tile_type,
            "tile_compression": Compression.NONE,
            "min_zoom": min_zoom,
            "max_zoom": max_zoom,
            # Bounds stored as integers (e7 = degrees × 10^7)
            "min_lon_e7": int(w * 10_000_000),
            "min_lat_e7": int(s * 10_000_000),
            "max_lon_e7": int(e * 10_000_000),
            "max_lat_e7": int(n * 10_000_000),
            "center_zoom": center_zoom,
            "center_lon_e7": int(center_lon * 10_000_000),
            "center_lat_e7": int(center_lat * 10_000_000),
        }

        self._metadata = {
            "name": name,
            "description": f"Created {datetime.datetime.now()}",
            "version": "1",
            "type": "baselayer",
            "encoding": encoding,
            "format": fmt,
            "minzoom": min_zoom,
            "maxzoom": max_zoom,
            "bounds": f"{w},{s},{e},{n}",
            "center": f"{center_lon},{center_lat},{center_zoom}",
        }

    def insert_tile_with_retry(
        self,
        tile: List[int],
        contents: bytes,
        use_inverse_y: bool = False,
    ):
        """Buffer a tile for later writing.

        Parameters
        ----------
        tile:
            ``[x, y, z]`` tile coordinates.
        contents:
            Raw image bytes.
        use_inverse_y:
            When *True* the y coordinate is in TMS (south-up) convention and
            will be flipped to the XYZ (north-up) convention that PMTiles uses.
        """
        x, y, z = tile
        if use_inverse_y:
            y = int(math.pow(2, z)) - y - 1
        tile_id = zxy_to_tileid(z, x, y)
        self._tiles[tile_id] = contents

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _finalise(self):
        """Sort buffered tiles by Hilbert tile ID and write the PMTiles archive."""
        if not self._tiles:
            logging.warning("PMTilesWriter: no tiles were buffered – writing empty archive.")

        sorted_ids = sorted(self._tiles.keys())

        logging.info(f"PMTilesWriter: writing {len(sorted_ids)} tiles to {self.outpath}")

        with open(self.outpath, "wb") as f:
            writer = Writer(f)
            for tile_id in sorted_ids:
                writer.write_tile(tile_id, self._tiles[tile_id])
            writer.finalize(self._header, self._metadata)

        logging.info(f"PMTilesWriter: finished writing {self.outpath}")
