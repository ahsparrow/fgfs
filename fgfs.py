# Copyright 2021 Alan Sparrow
#
# This file is part of IGCVis
#
# IGCVis is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Navplot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with IGCVis.  If not, see <http://www.gnu.org/licenses/>.

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

TDELTA = 0.1

# Parse IGC UTC value
def parse_utc(utc):
    h, ms = divmod(int(utc), 10000)
    m, s = divmod(ms, 100)

    return h * 3600 + m * 60 + s

# Create FGFS data
def format_fgfs(lat, lon, start, duration, t, xyz, hrp):
    try:
        # Get start/stop indices
        stop = start + duration
        n = np.where(t == start)[0][0]
        m = np.where(t == stop)[0][0]
    except IndexError:
        return None

    xyz1 = xyz[:, n:m]
    hrp1 = hrp[:, n:m]

    # Time step size
    tdelta = t[1] - t[0]

    # Convert local X/Y/Z to ECEF
    transformer = Transformer.from_crs(igc.EPSG_XY, EPSG_ECEF)
    xec, yec, zec = transformer.transform(xyz1[1], xyz1[0], xyz1[2])

    # Calculate ECEF speed components
    vx = igc.speed(xec, tdelta, 5)
    vy = igc.speed(yec, tdelta, 5)
    vz = igc.speed(zec, tdelta, 5)

    # Rotate orientation from local to ECEF
    view_attitude = Rotation.from_euler("zyx", [0, 0, 0], degrees=True).as_matrix()

    # Rotate to view
    rot = Rotation.from_euler("zyx", [-lon, lat, 0], degrees=True)
    view_attitude = rot.apply(view_attitude)

    # Swap axes
    rot = Rotation.from_euler("zyx", [0, 90, 0], degrees=True)
    view_attitude = rot.apply(view_attitude)

    orientations = []
    for h, r, p in hrp1.transpose():
        # Set attitude
        rot = Rotation.from_euler("zyx", [-h, -p, -r], degrees=True)
        ecef_attitude = rot.apply(view_attitude)

        # Convert to rotation vector
        orientation = Rotation.from_matrix(ecef_attitude).as_rotvec()
        orientations.append(orientation)

    orientations = np.array(orientations).transpose()

    # Combine data into 2D array
    fgfs_data = np.stack(
        (xec, yec, zec, orientations[0], orientations[1], orientations[2], vx, vy, vz),
        axis=1)

    return fgfs_data

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('elevation', type=float, help='takeoff elevation (m)')
    parser.add_argument('igc', nargs='+',
                        type=argparse.FileType('r', errors=None),
                        help='IGC log file')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-d', '--diag', action='store_true',
                        help='diagnostic plots')
    group.add_argument('-f', '--file', type=argparse.FileType('wt'),
                        help="JSON Output file")
    parser.add_argument('-s', '--start', type=int,
                        help='UTC start time (format 130415)')
    parser.add_argument('-t', '--duration', type=int,
                        help='duration (s)')
    parser.add_argument('-w', '--wind_dir', type=float, default=0.0,
                        help='wind direction')
    parser.add_argument('-v',  '--wind_speed', type=float, default=0.0,
                        help='wind speed (kts), default 0 kts')
    parser.add_argument('-g', '--geoid', type=float, default=48.0,
                        help='geoid height (m), default 48 m')
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
        alt, cal_errors = igc.calibrate_altitude(alt_pressure, alt_geoid,
                errors=True)

        # Convert and interpolate to local X/Y/Z
        t, xyz = igc.resample_xyz(utc, lat, lon, alt, TDELTA)

        # Calculate flight dynamics
        xyz1, hrp = igc.dynamics(xyz, TDELTA, args.wind_speed, args.wind_dir)

        if args.file:
            # Output data for Flightgear
            start = parse_utc(args.start)

            # Get data for FGFS
            out = format_fgfs(data['lat'].mean(), data['lon'].mean(),
                    start, args.duration, t, xyz, hrp)

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

            axs[0][1].plot(cal_errors)

            axs[1][0].plot(xyz[0], xyz[1])
            axs[1][0].set_aspect('equal')

            axs[1][1].plot(xyz1[0], xyz[1])
            axs[1][1].set_aspect('equal')

            pyplot.show()

    # Write FGFS data to file
    if args.file:
        start_time = dt.strptime(log_date + "%06d" % args.start, '%d%m%y%H%M%S').isoformat()
        data = {'start': start_time,
                'tdelta': TDELTA,
                'ids': ids,
                'logs': logs}
        json.dump(data, args.file)
