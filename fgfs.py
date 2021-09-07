import argparse
from datetime import datetime as dt
import itertools
import json
import logging
import sys

import numpy as np
from pyproj import Transformer
from scipy.spatial.transform import Rotation

import igc
from igcparser import parse_igc

EPSG_ECEF = 4978

# Parse IGC UTC value
def parse_utc(utc):
    h, ms = divmod(int(utc), 10000)
    m, s = divmod(ms, 100)

    return h * 3600 + m * 60 + s

# Create FGFS data
def fgfs_data(lat, lon, start, stop, t, x, y, z, heading, roll, pitch):
    try:
        # Get start/stop indices
        n = np.where(t == start)[0][0]
        m = np.where(t == stop)[0][0]
    except IndexError:
        return None

    # Time step size
    tdelta = t[1] - t[0]

    # Convert local X/Y/Z to ECEF
    transformer = Transformer.from_crs(igc.EPSG_XY, EPSG_ECEF)
    xec, yec, zec = transformer.transform(y[n:m], x[n:m], z[n:m])

    # Calculate ECEF speed components
    vx = igc.speed(xec, tdelta, 5)
    vy = igc.speed(yec, tdelta, 5)
    vz = igc.speed(zec, tdelta, 5)

    # Rotate orientation from local to ECEF
    ori_arr = []

    # Initial orientation
    view_attitude = Rotation.from_euler("zyx", [0, 0, 0], degrees=True).as_matrix()

    # Rotate to view
    rot = Rotation.from_euler("zyx", [-lon, lat, 0], degrees=True)
    view_attitude = rot.apply(view_attitude)

    # Swap axes
    rot = Rotation.from_euler("zyx", [0, 90, 0], degrees=True)
    view_attitude = rot.apply(view_attitude)

    for i in range(n, m):
        # Set attitude
        rot = Rotation.from_euler("zyx", [-heading[i], -pitch[i], -roll[i]], degrees=True)
        ecef_attitude = rot.apply(view_attitude)

        # Convert to rotation vector
        ori = Rotation.from_matrix(ecef_attitude).as_rotvec()
        ori_arr.append(ori)

    out = np.array(ori_arr).transpose()

    return np.transpose(np.vstack(
        (xec, yec, zec, out[0], out[1], out[2], vx, vy, vz)))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('elevation', type=float, help='Takeoff elevation')
    parser.add_argument('igc', nargs='+',
                        type=argparse.FileType('r', errors=None),
                        help='IGC log file')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-f', '--file', type=argparse.FileType('wt'),
                        help="JSON Output file")
    group.add_argument('--diag', action='store_true',
                        help='Make diagnostic plots')
    parser.add_argument('-s', '--start', type=int,
                        help='UTC start time (format 130415)')
    parser.add_argument('-d', '--duration', type=int,
                        help='Duration (s)')
    parser.add_argument('-t', '--tdelta', type=float, default=0.1,
                        help='Output time sample (s), default 0.1 s')
    parser.add_argument('-w',  '--wind_speed', type=float, default=0.0,
                        help='Wind speed (kts), default 0 kts')
    parser.add_argument('-r', '--wind_dir', type=float, default=0.0,
                        help='Wind direction')
    parser.add_argument('-g', '--geoid', type=float, default=48.0,
                        help='Geoid height (m), default 48 m')
    args = parser.parse_args()

    if args.file and not (args.start and args.duration):
        parser.print_usage()
        print("error: start and duration are required")
        sys.exit(2)

    logs = []
    ids = []
    for igc_file in args.igc:
        # Read IGC file
        print("Reading %s" % igc_file.name)
        hdr, data = parse_igc(igc_file)
        id = hdr.get('cid') or hdr.get('gid') or hdr['id']

        # Discard first few samples
        data = data[5:]

        utc, lat, lon = data['utc'], data['lat'], data['lon']
        alt_pressure, alt_gps = data['alt'], data['alt_gps']

        # Get sample interval
        tdelta_igc = igc.get_tdelta(utc)
        if tdelta_igc > 4:
            logging.warning("skipping, sample interval > 4 s, %d s" % tdelta_igc)
            continue

        # Convert to geoid referenced GPS
        alt_geoid = igc.check_geoid(alt_gps, args.elevation, args.geoid)

        # Convert to calibrated pressure altitude
        alt = igc.calibrate_altitude(alt_pressure, alt_geoid)

        # Convert and interpolate to local X/Y/Z
        t, x, y, z = igc.resample_xyz(utc, lat, lon, alt, args.tdelta)

        # Calculate flight dynamics
        x1, y1, heading, roll, pitch = igc.dynamics(x, y, z, args.tdelta,
                args.wind_speed, args.wind_dir)

        if args.file:
            # Output data for Flightgear
            start = parse_utc(args.start)
            stop = parse_utc(args.start + args.duration)

            # Get data for FGFS
            out = fgfs_data(data['lat'].mean(), data['lon'].mean(),
                    start, stop, t, x, y, z, heading, roll, pitch)

            if not out is None:
                ids.append(id)
                logs.append({'data': out.tolist(), 'id': id})

                log_date = hdr.get('dte')
            else:
                logging.warning("no data found")
        else:
            # Diagnostic plots
            from matplotlib import pyplot

            # Plot diagnostics
            fix, axs = pyplot.subplots(2, 2)
            axs[0][0].plot(alt_gps)

            axs[0][1].plot(alt_gps - alt)

            axs[1][0].plot(x, y)
            axs[1][0].set_aspect('equal')

            axs[1][1].plot(x1, y1)
            axs[1][1].set_aspect('equal')

            pyplot.show()

    if args.file:
        start_time = dt.strptime(log_date + "%06d" % args.start, '%d%m%y%H%M%S').isoformat()
        data = {'start': start_time, 'tdelta': args.tdelta, 'ids': ids,
                'logs': logs}
        json.dump(data, args.file)
