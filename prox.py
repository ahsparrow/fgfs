import argparse
import itertools
import logging
from datetime import datetime as dt

import numpy as np

import igc
from igcparser import parse_igc

TDELTA = 1

# Return new data filtered by minimum speed
def speed_filter(data, min_speed):
    t, x, y, z = np.transpose(data)

    vx = igc.speed(x, TDELTA, 3)
    vy = igc.speed(y, TDELTA, 3)

    v = np.sqrt(vx * vx + vy * vy)

    return data[vx > min_speed]

def find_near_misses(logs, threshold):
    for log1, log2 in itertools.permutations(logs, 2):
        # Filter speed less than approx 20kts
        data1 = speed_filter(log1['data'], 10)
        data2 = speed_filter(log2['data'], 10)

        # Find command time samples
        t1, x1, y1, z1 = np.transpose(data1)
        t2, x2, y2, z2 = np.transpose(data2)
        i, c1, c2 = np.intersect1d(t1, t2, return_indices=True)

        # Select common times from the two logs
        data1c = data1[c1]
        data2c = data2[c2]

        # Calculate distance between logs
        xyz1 = np.array([(x[1], x[2], x[3]) for x in data1c])
        xyz2 = np.array([(x[1], x[2], x[3]) for x in data2c])
        dist = np.linalg.norm(xyz1 - xyz2, axis=1)

        # Find near miss indices
        idx = np.where(dist < threshold)[0]
        if len(idx) > 0:
            print('%s -> %s' % (log1['id'], log2['id']))

            # Split into non-consecutive time periods
            hits = np.split(idx, np.where(np.diff(idx) != 1)[0] + 1)
            for hit in hits:
                # Find closest approach
                hit_min_idx = np.argmin(dist[hit])
                min_idx = hit[hit_min_idx]

                utc = dt.utcfromtimestamp(t1[min_idx])
                utc_str = utc.strftime("%H:%M:%S")
                print("  %s %.1fm" % (utc_str, dist[min_idx]))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('elevation', type=float, help='Takeoff elevation')
    parser.add_argument('dist', type=float, help='Near miss distance (m)')
    parser.add_argument('igc', nargs='+',
                        type=argparse.FileType('r', errors=None),
                        help='IGC log file')
    parser.add_argument('-g', '--geoid', type=float, default=48.0,
                        help='Geoid height (m), default 48m')
    args = parser.parse_args()

    logs = []
    for igc_file in args.igc:
        print("Reading %s" % igc_file.name)
        hdr, data = parse_igc(igc_file)
        id = hdr.get('cid') or hdr.get('gid') or hdr['id']

        tdelta_igc = igc.check(data)
        if tdelta_igc > 4:
            logging.warning("sample interval > 4 s, %d s" % tdelta_igc)
            continue

        # Convert to X/Y/Z
        t, x, y, z = igc.interpolate_xyz(hdr, data, tdelta_igc, TDELTA,
                args.elevation, args.geoid)

        data = np.transpose(np.vstack((t, x, y, z)))
        logs.append({'id': id, 'data': data})

    print("Searching for near misses...")
    find_near_misses(logs, args.dist)
