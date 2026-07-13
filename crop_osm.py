#!/usr/bin/env python3
"""
crop_osm.py — crop and strip a bbbike.org .osm export down to just what
the Then/Now map renderer needs.

WHY THIS EXISTS
bbbike exports include full editing history (version, timestamp, user,
changeset) plus every tag on every node/way, even ones the renderer never
draws (parking aisles, address points, power lines, etc). That bloats a
city-sized extract to 40-50MB, which is too much for a phone browser to
parse smoothly. This script:
  1. Crops to a bounding box around your marker(s)
  2. Keeps only ways tagged as building / water / road / footpath / park
  3. Drops highway=service (driveways, parking lanes — usually just clutter)
  4. Strips all metadata attributes down to bare id/lat/lon and the handful
     of tags the renderer actually reads

USAGE
  1. Download a fresh extract from bbbike.org (OSM XML, gzip) for your area,
     or a tighter box once you know exactly which photos you're covering.
  2. Unzip it (gunzip yourfile.osm.gz) so you have plain "yourfile.osm".
  3. Edit CENTER_LAT / CENTER_LON / HALF_KM below to match your photo set's
     extent (or pass them as command-line args — see bottom of file).
  4. Run:  python3 crop_osm.py yourfile.osm map.osm
  5. Drop the resulting map.osm next to the app's index.html.

You can safely re-run this every time you get a new export — nothing here
needs to change unless you add new feature types to FEATURE_STYLES in the
app's JS and want this script's KEEP logic to match.
"""

import sys
import math
import xml.etree.ElementTree as ET

# ---- default crop center (Stratford Stone Bridge) — override via CLI args ----
CENTER_LAT = 43.37032
CENTER_LON = -80.98185
HALF_KM = 0.9  # crop box is roughly (2 * HALF_KM) kilometers wide/tall

# tags that make a way worth keeping, and (where relevant) which values count
RELEVANT_VALUES = {
    'natural': {'water', 'wood'},
    'waterway': {'river', 'riverbank', 'stream'},
    'highway': {
        'primary', 'secondary', 'tertiary', 'residential', 'unclassified',
        'footway', 'path', 'pedestrian', 'living_street'
        # NOTE: 'service' intentionally excluded — driveways/parking aisles,
        # usually too noisy at this scale. Add it back here if you want it.
    },
    'leisure': {'park'},
    'landuse': {'grass', 'forest', 'recreation_ground', 'meadow'},
}

# tags copied into the output (kept minimal on purpose)
KEEP_TAG_KEYS = {'building', 'natural', 'waterway', 'highway', 'leisure', 'landuse', 'bridge', 'name'}


def in_box(lat, lon, minlat, maxlat, minlon, maxlon):
    return minlat <= lat <= maxlat and minlon <= lon <= maxlon


def way_is_relevant(tags):
    if 'building' in tags:
        return True
    if tags.get('bridge') == 'yes':
        return True
    for k, allowed_values in RELEVANT_VALUES.items():
        if tags.get(k) in allowed_values:
            return True
    return False


def crop_and_strip(input_path, output_path, center_lat, center_lon, half_km):
    dlat = half_km / 111.32
    dlon = half_km / (111.32 * math.cos(math.radians(center_lat)))
    minlat, maxlat = center_lat - dlat, center_lat + dlat
    minlon, maxlon = center_lon - dlon, center_lon + dlon

    print(f"Crop box: lat [{minlat:.5f}, {maxlat:.5f}]  lon [{minlon:.5f}, {maxlon:.5f}]")

    # Pass 1: index all node coordinates (needed to resolve way geometry)
    print("Indexing nodes...")
    nodes = {}
    for _, elem in ET.iterparse(input_path, events=('end',)):
        if elem.tag == 'node':
            nodes[elem.get('id')] = (float(elem.get('lat')), float(elem.get('lon')))
            elem.clear()
    print(f"  {len(nodes)} nodes total")

    # Pass 2: find relevant ways with at least one node inside the box
    print("Filtering ways...")
    kept_ways = []
    for _, elem in ET.iterparse(input_path, events=('end',)):
        if elem.tag == 'way':
            tags = {t.get('k'): t.get('v') for t in elem.findall('tag')}
            if way_is_relevant(tags):
                refs = [nd.get('ref') for nd in elem.findall('nd')]
                coords = [nodes[r] for r in refs if r in nodes]
                if coords and any(in_box(lat, lon, minlat, maxlat, minlon, maxlon) for lat, lon in coords):
                    kept_ways.append({'refs': refs, 'tags': tags})
            elem.clear()
    print(f"  {len(kept_ways)} ways kept")

    used_node_ids = set()
    for w in kept_ways:
        used_node_ids.update(w['refs'])
    print(f"  {len(used_node_ids)} nodes referenced")

    # Write stripped XML
    print(f"Writing {output_path}...")
    with open(output_path, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<osm version="0.6" generator="crop_osm.py">\n')
        for nid in used_node_ids:
            lat, lon = nodes[nid]
            f.write(f'<node id="{nid}" lat="{lat:.5f}" lon="{lon:.5f}"/>\n')
        for i, w in enumerate(kept_ways):
            f.write(f'<way id="w{i}">\n')
            for r in w['refs']:
                if r in used_node_ids:
                    f.write(f'<nd ref="{r}"/>\n')
            for k, v in w['tags'].items():
                if k in KEEP_TAG_KEYS:
                    v_esc = v.replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                    f.write(f'<tag k="{k}" v="{v_esc}"/>\n')
            f.write('</way>\n')
        f.write('</osm>\n')

    import os
    size_kb = os.path.getsize(output_path) / 1024
    print(f"Done. {output_path} is {size_kb:.1f} KB")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        print("Usage: python3 crop_osm.py <input.osm> <output.osm> [center_lat] [center_lon] [half_km]")
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]
    lat = float(sys.argv[3]) if len(sys.argv) > 3 else CENTER_LAT
    lon = float(sys.argv[4]) if len(sys.argv) > 4 else CENTER_LON
    half_km = float(sys.argv[5]) if len(sys.argv) > 5 else HALF_KM

    crop_and_strip(in_path, out_path, lat, lon, half_km)
