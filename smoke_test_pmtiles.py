import tempfile, os, sys
from rio_rgbify.pmtiles_writer import PMTilesWriter

with tempfile.NamedTemporaryFile(suffix='.pmtiles', delete=False) as f:
    outpath = f.name

writer = PMTilesWriter(outpath)
with writer:
    writer.add_bounds_center_metadata([-180, -85, 180, 85], 0, 3, 'mapbox', 'png')
    fake_tile = b'PNG_FAKE_TILE_BYTES'
    writer.insert_tile_with_retry([0, 0, 0], fake_tile, use_inverse_y=True)
    writer.insert_tile_with_retry([0, 1, 1], fake_tile, use_inverse_y=True)
    writer.commit()

size = os.path.getsize(outpath)
print(f'PMTiles written: {outpath} ({size} bytes)')

# Verify it reads back
sys.path.insert(0, 'PMTiles/python/pmtiles')
from pmtiles.reader import Reader, MmapSource
with open(outpath, 'rb') as f:
    reader = Reader(MmapSource(f))
    h = reader.header()
    print(f'min_zoom={h["min_zoom"]} max_zoom={h["max_zoom"]}')
    tile = reader.get(0, 0, 0)
    print(f'Tile z0/x0/y0: {tile}')

os.unlink(outpath)
print('Smoke test PASSED')
