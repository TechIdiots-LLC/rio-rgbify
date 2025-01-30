from __future__ import with_statement
from __future__ import division

import traceback
import itertools
import mercantile
import rasterio
import numpy as np
from multiprocessing import get_context, cpu_count
import os
from rasterio import transform
from rasterio.warp import reproject, transform_bounds
from rasterio.enums import Resampling
from rio_rgbify.database import MBTilesDatabase
from rio_rgbify.image import ImageEncoder
import logging
import signal
import functools
import psutil

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def process_tile(inpath, format, encoding, interval, base_val, round_digits, resampling, quantized_alpha, tile, verbose):
    """Standalone tile processing function"""
    # Log the process ID and CPU core
    proc = psutil.Process()
    if verbose:
        logging.info(f"Processing tile  on CPU {proc.cpu_num()} (PID: {os.getpid()})")
    
    if not isinstance(tile, (tuple,list)):
        logging.error(f"process_tile: Invalid tile type: {type(tile)}. Value: {tile}")
        return None
    
    try:
        if verbose:
            print(f"process_tile: Attempting to open {inpath}")
        with rasterio.open(inpath) as src:
            x, y, z = tile
            if verbose:
              print(f"process_tile: Opened {inpath} for tile {tile}")

            bounds = [
                c
                for i in (
                    mercantile.xy(*mercantile.ul(x, y + 1, z)),
                    mercantile.xy(*mercantile.ul(x + 1, y, z)),
                )
                for c in i
            ]

            toaffine = transform.from_bounds(*bounds + [512, 512])

            out = np.empty((512, 512), dtype=src.meta["dtype"])
            if verbose:
                print(f"process_tile: About to reproject for tile {tile}")

            reproject(
                rasterio.band(src, 1),
                out,
                dst_transform=toaffine,
                dst_crs="EPSG:3857",
                resampling=resampling,
            )
            if verbose:
              print(f"process_tile: Reprojected tile {tile}, out shape: {out.shape}")
              print(f"process_tile: data before data_to_rgb: min={np.nanmin(out)}, max={np.nanmax(out)}, type: {out.dtype}")

            rgb = ImageEncoder.data_to_rgb(out, encoding, interval, base_val, round_digits, quantized_alpha)
            if verbose:
              print(f"process_tile: data after data_to_rgb: min={np.nanmin(rgb)}, max={np.nanmax(rgb)}, type: {rgb.dtype}")
            result = ImageEncoder.save_rgb_to_bytes(rgb, format)
            
            if verbose:
              print(f"process_tile: Encoded tile {tile}")

            return tile, result
            
    except Exception as e:
        logging.error(f"Error processing tile {tile}: {str(e)}")
        logging.error(f"process_tile: Error for tile {tile}: {traceback.format_exc()}") # more details for the traceback
        return None

class RGBTiler:
    """
    Takes continuous source data of an arbitrary bit depth and encodes it
    in parallel into RGB tiles in an MBTiles file. Provided with a context manager:
    ```
    with RGBTiler(inpath, outpath, min_z, max_x) as tiler:
        tiler.run(processes)
    ```

    Parameters
    -----------
    inpath: string
        filepath of the source file to read and encode
    outpath: string
        filepath of the output `mbtiles`
    min_z: int
        minimum zoom level to tile
    max_z: int
        maximum zoom level to tile

    Keyword Arguments
    ------------------
    baseval: float
        the base value of the RGB numbering system.
        (will be treated as zero for this encoding)
        Default=0
    interval: float
        the interval at which to encode
        Default=1
    round_digits: int
        Erased less significant digits
        Default=0
    encoding: str
        output tile encoding (mapbox or terrarium)
        Default=mapbox
    format: str
        output tile image format (png or webp)
        Default=png
    bounding_tile: list
        [x, y, z] of bounding tile; limits tiled output to this extent

    Returns
    --------
    None

    """

    def __init__(
        self,
        inpath,
        outpath,
        min_z,
        max_z,
        interval=0.1, # updated default
        base_val=-10000, # updated default
        round_digits=0,
        encoding="mapbox",
        format="webp",
        resampling=Resampling.nearest,
        quantized_alpha=True,
        bounding_tile=None,
    ):
        self.inpath = inpath
        self.outpath = outpath
        self.min_z = min_z
        self.max_z = max_z
        self.bounding_tile = bounding_tile
        self.encoding = encoding
        self.format = format
        self.interval = interval
        self.base_val = base_val
        self.round_digits = round_digits
        self.resampling = resampling
        self.quantized_alpha = quantized_alpha

    @staticmethod
    def _tile_range(min_tile, max_tile):
        """
        Given a min and max tile, return an iterator of
        all combinations of this tile range

        Parameters
        -----------
        min_tile: list
            [x, y, z] of minimun tile
        max_tile:
            [x, y, z] of minimun tile

        Returns
        --------
        tiles: iterator
            iterator of [x, y, z] tiles
        """
        min_x, min_y, _ = min_tile
        max_x, max_y, _ = max_tile

        return itertools.product(range(min_x, max_x + 1), range(min_y, max_y + 1))

    def _make_tiles(self, bbox, src_crs, minz, maxz, verbose=False):
        """
        Given a bounding box, zoom range, and source crs,
        find all tiles that would intersect

        Parameters
        -----------
        bbox: list
            [w, s, e, n] bounds
        src_crs: str
            the source crs of the input bbox
        minz: int
            minumum zoom to find tiles for
        maxz: int
            maximum zoom to find tiles for

        Returns
        --------
        tiles: generator
            generator of [x, y, z] tiles that intersect
            the provided bounding box
        """
        w, s, e, n = transform_bounds(*[src_crs, "EPSG:4326"] + bbox)

        EPSILON = 1.0e-10

        w += EPSILON
        s += EPSILON
        e -= EPSILON
        n -= EPSILON
        
        print(f"_make_tiles: bbox: {bbox}, src_crs: {src_crs}, minz: {minz}, maxz: {maxz}")


        for z in range(minz, maxz + 1):
            for x, y in RGBTiler._tile_range(mercantile.tile(w, n, z), mercantile.tile(e, s, z)):
              if verbose:
                print(f"_make_tiles: yielding tile {x}, {y}, {z}")
              yield [x, y, z]


    def _init_worker(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    def run(self, processes=None, batch_size=None, verbose=False):
        """Main processing loop with smart process scaling"""
        with rasterio.open(self.inpath) as src:
            # Set up bounds and tiles
            if self.bounding_tile is None:
                bbox = list(src.bounds)
                tiles = list(self._make_tiles(bbox, src.crs, self.min_z, self.max_z, verbose=verbose))
                bounds = transform_bounds(src.crs, "EPSG:4326", *bbox)
            else:
                constrained_bbox = list(mercantile.bounds(self.bounding_tile))
                tiles = list(self._make_tiles(constrained_bbox, "EPSG:4326", self.min_z, self.max_z, verbose=verbose))
                bounds = constrained_bbox

            total_tiles = len(tiles)
            print(f"Total tiles to process: {total_tiles}")

            # Smart process scaling
            if processes is None or processes <= 0:
                processes = max(1, cpu_count() - 1)  # Leave one CPU free
            processes = min(total_tiles, processes)

            # Calculate initial batch size
            if batch_size is None:
                batch_size = max(1, min(1000, total_tiles // (processes * 2)))

            print(f"Running with {processes} processes and initial batch size of {batch_size}")

        # Set up multiprocessing
        ctx = get_context("fork")
        process_func = functools.partial(
            process_tile,
            self.inpath,
            self.format,
            self.encoding,
            self.interval,
            self.base_val,
            self.round_digits,
            self.resampling,
            self.quantized_alpha,
            verbose=verbose
        )

        with self.db:
            # Add metadata
            if self.bounding_tile is None:
                self.db.add_bounds_center_metadata(bbox, self.min_z, self.max_z, self.encoding, self.format, "Terrain")
            else:
                self.db.add_bounds_center_metadata(constrained_bbox, self.min_z, self.max_z, self.encoding, self.format, "Terrain")

            with ctx.Pool(processes, initializer=self._init_worker) as pool:
                try:
                    total_processed = 0
                    tiles_remaining = tiles  # Start with all tiles

                    while tiles_remaining:
                        # Dynamically adjust chunk size based on remaining tiles and processes
                        remaining_count = len(tiles_remaining)
                        current_chunk_size = min(
                            batch_size,
                            max(1, remaining_count // processes)
                        )
                        
                        # Process current batch
                        current_batch = tiles_remaining[:current_chunk_size * processes]
                        tiles_remaining = tiles_remaining[current_chunk_size * processes:]

                        print(f"Processing batch with chunk size: {current_chunk_size}")
                        print(f"Remaining tiles: {remaining_count}")
                        print(f"Active processes: {len(pool._pool)}")

                        # Process the current batch
                        for result in pool.imap_unordered(process_func, current_batch, chunksize=current_chunk_size):
                            if result:
                                self.db.insert_tile_with_retry(*result, use_inverse_y=True)
                                total_processed += 1
                                
                                if total_processed % 100 == 0:  # Progress update
                                    print(f"Processed {total_processed}/{total_tiles} tiles")

                        # Commit after each batch
                        self.db.conn.commit()
                        print(f"Committed batch to database. {total_processed}/{total_tiles} total tiles processed")

                except KeyboardInterrupt:
                    print("Caught KeyboardInterrupt, terminating workers")
                    pool.terminate()
                    raise
                except Exception as e:
                    logging.error(f"Error in processing: {str(e)}")
                    pool.terminate()
                    raise
                finally:
                    pool.close()
                    pool.join()

    def __enter__(self):
        try:
            self.db = MBTilesDatabase(self.outpath)
        except Exception as e:
            logging.error(f"Failed to initialize database: {e}")
            self.db = None
            raise
        return self

    def __exit__(self, ext_t, ext_v, trace):
        if self.db:
            if ext_t:
                traceback.print_exc()
