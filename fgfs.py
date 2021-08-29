import argparse
import csv
import datetime
import itertools
import json
import logging
import sys

from matplotlib import pyplot
import numpy as np
from pyproj import Transformer
from scipy.interpolate import splrep, splev
from scipy.spatial.transform import Rotation
from scipy.stats import mode

from igcparser import parse_igc

EPSG_WGS84 = 4326
EPSG_XY = 3035
EPSG_ECEF = 4978

# Apply simple running average
def filter(data, n):
    # Filter length must be odd
    n1 = int(n // 2) * 2 + 1

    kernel = np.ones(n1) / n1
    m = n1 // 2

    # Pad data to minimise end effects
    pad = np.ones(m)
    d = np.concatenate((pad * data[0], data, pad * data[-1]))

    out = np.convolve(d, kernel, mode='valid')
    return out

# Parse IGC UTC value
def parse_utc(utc):
    h, ms = divmod(utc, 10000)
    m, s = divmod(ms, 100)

    return h * 3600 + m * 60 + s

# Caculate speed from 1-D array of positions
def calc_speed(x, td, tavg):
    v = np.diff(x, append=x[-1:]) / td
    vs = filter(v, tavg / td)
    return vs

def check_igc(data):
    # Sample interval
    res = mode(np.diff(data['utc']))
    delta_t = res.mode[0]
    return delta_t

# Fuse GPS and pressure altitudes
def fuse_altitude(alt_pressure, alt_gps, delta_t):
    delta_alt = filter(alt_gps - alt_pressure, 60 / delta_t)
    alt_fuse = alt_pressure + delta_alt

    return alt_fuse

# Convert to local X/Y coordinates and resample data
def xyz_resample(utc, lat, lon, alt, resample_t):
    # Convert to local x/y coordinates
    transformer = Transformer.from_crs(EPSG_WGS84, EPSG_XY)
    y, x = transformer.transform(lat, lon)

    # Resample using cubic splines
    n = round((utc[-1] - utc[0]) / resample_t) + 1
    t = (np.arange(n) * resample_t) + utc[0]

    x1 = splev(t, splrep(utc, x, s=0), der=0)
    y1 = splev(t, splrep(utc, y, s=0), der=0)
    z1 = splev(t, splrep(utc, alt, s=0), der=0)

    return t, x1, y1, z1

# Calculate flight dynamics, heading, roll, etc.
def calc_dynamics(x, y, z, tdelta, wind_speed, wind_dir):
    wind_speed = wind_speed * 1852 / 3600
    wind_dir = np.radians(wind_dir)

    # Correct for wind velocity
    n = len(x)
    wind_x = np.arange(n) * wind_speed * tdelta * np.sin(wind_dir)
    wind_y = np.arange(n) * wind_speed * tdelta * np.cos(wind_dir)
    xw = x + wind_x
    yw = y + wind_y

    # Calculate heading
    xdelta = np.diff(xw, append=xw[-1:])
    ydelta = np.diff(yw, append=yw[-1:])
    heading = np.degrees(np.arctan2(xdelta, ydelta))

    unwrapped_heading = np.unwrap(np.radians(heading))
    av_unwrapped_heading = filter(unwrapped_heading, 4 / tdelta)

    # Calculate speed
    speed = np.sqrt(xdelta ** 2  + ydelta ** 2) / tdelta
    speed = filter(speed, 5 / tdelta)

    # Bank angle
    omega = np.diff(unwrapped_heading, append=unwrapped_heading[-1:]) / tdelta
    theta = np.degrees(np.arctan(omega * speed / 9.81))

    av_theta = filter(theta, 5 / tdelta)

    # Pitch angle
    zdelta = np.diff(z, append=z[-1:])
    pitch = np.degrees(zdelta / (speed * tdelta))
    pitch = filter(pitch, 2 / tdelta)

    return xw, yw, np.mod(np.degrees(av_unwrapped_heading), 360), av_theta, pitch 

# Create FGFS data
def fgfs_data(lat, lon, start, stop, t, x, y, z, heading, roll, pitch, xyz_only=False):
    try:
        # Get start/stop indices
        n = np.where(t == start)[0][0]
        m = np.where(t == stop)[0][0]
    except IndexError:
        return None

    # Time step size
    tdelta = t[1] - t[0]

    # Convert local X/Y/Z to ECEF
    transformer = Transformer.from_crs(EPSG_XY, EPSG_ECEF)
    xec, yec, zec = transformer.transform(y[n:m], x[n:m], z[n:m])

    # Calculate ECEF speed components
    vx = calc_speed(xec, tdelta, 5)
    vy = calc_speed(yec, tdelta, 5)
    vz = calc_speed(zec, tdelta, 5)

    # Rotation
    if xyz_only:
        # XYZ only - to speed up near miss calculation
        ori_arr = np.zeros((m - n, 3))
    else:
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

def near_misses(logs, threshold, start, tdelta):
    for log in itertools.combinations(logs, 2):
        # Calculate distance between logs
        xyz1 = np.array([(x[0], x[1], x[2]) for x in log[0]['data']])
        xyz2 = np.array([(x[0], x[1], x[2]) for x in log[1]['data']])
        dist = np.linalg.norm(xyz1 - xyz2, axis=1)

        # Find near miss indices
        idx = np.where(dist < threshold)[0]
        if len(idx) > 0:
            print('%s -> %s' % (log[0]['id'], log[1]['id']))

            # Split into non-consecutive time periods
            hits = np.split(idx, np.where(np.diff(idx) != 1)[0] + 1)
            for hit in hits:
                # Find closest approach
                hit_min_idx = np.argmin(dist[hit])
                min_idx = hit[hit_min_idx]

                utc = datetime.datetime.utcfromtimestamp(start + min_idx * tdelta)
                utc_str = utc.strftime("%H:%M:%S")
                print("%s %.1f" % (utc_str, dist[min_idx]))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("outfile", type=argparse.FileType('wt'),
                        help="JSON Output file")
    parser.add_argument('igc', nargs='+',
                        type=argparse.FileType('r', errors=None),
                        help='IGC files with ellipsoid datum')
    parser.add_argument('--start', type=int, required=True,
                        help='UTC start time (format 130415)')
    parser.add_argument('--stop', type=int, required=True,
                        help='UTC end time (format 131030)')
    parser.add_argument('--wind_speed', '-w', type=float, default=0.0,
                        help='Wind speed (kts), default 0kts')
    parser.add_argument('--wind_dir', '-d', type=float, default=0.0,
                        help='Wind direction')
    parser.add_argument('--tdelta', '-t', type=float, default=0.1,
                        help='Output time sample (s), default 0.1s')
    parser.add_argument('--geoid', '-g', type=float, default=48.0,
                        help='Geoid height (m), default 48m')
    parser.add_argument('--elev', type=float, required=True,
                        help='Takeoff elevation')
    parser.add_argument('--diag', action='store_true',
                        help='Make diagnostic plots')
    parser.add_argument('--dist', type=float, default=0.0,
                        help='Near miss distance (m)')
    args = parser.parse_args()

    # Time parameters
    start = parse_utc(args.start)
    stop = parse_utc(args.stop)

    logs = []
    ids = []
    for igc_file in args.igc:
        print("Reading %s" % igc_file.name)
        hdr, data = parse_igc(igc_file)

        # Bug in some loggers - remove duplicate samples
        u, idx = np.unique(data['utc'], return_index=True)
        data = data[idx]

        delta_t_igc = check_igc(data)
        if delta_t_igc > 4:
            logging.warning("sample interval > 4s, %.1f" % delta_t)
            continue

        utc, lat, lon = data['utc'], data['lat'], data['lon']
        alt_p, alt_g = data['alt'], data['alt_gps']

        # Fuse pressure and GPS altitudes
        alt = fuse_altitude(alt_p, alt_g, delta_t_igc)

        # Correct for geoid/ellipsoid altitude reference
        takeoff_alt = np.mean(alt_g[:10])

        err_geoid = abs(takeoff_alt - args.elev)
        err_ellip = abs((takeoff_alt - args.geoid) - args.elev)

        if (err_ellip < err_geoid):
            alt = alt - args.geoid

        min_err = min(err_ellip, err_geoid)
        if min_err > 10:
            logging.warning("Takeoff elevation error exceeds 10m: %.1f" % min_err)

        # Interpolate and convert to local X/Y/Z coordinates
        t, x, y, z = xyz_resample(utc, lat, lon, alt, args.tdelta)

        # Calculate flight dynamics
        x1, y1, heading, roll, pitch = calc_dynamics(x, y, z, args.tdelta,
                args.wind_speed, args.wind_dir)

        # Get data for FGFS
        out = fgfs_data(lat.mean(), lon.mean(),
                start, stop, t, x, y, z, heading, roll, pitch,
                xyz_only=(args.dist != 0))

        if not out is None:
            id = hdr.get('cid') or hdr.get('gid') or hdr['id']
            ids.append(id)
            logs.append({'data': out.tolist(), 'id': id})
        else:
            logging.warning("No data found")

        # Plot diagnostics
        if args.diag:
            fix, axs = pyplot.subplots(2, 2)
            axs[0][0].plot(alt_g)

            axs[0][1].plot(pitch)

            axs[1][0].plot(x, y)
            axs[1][0].set_aspect('equal')

            axs[1][1].plot(x1, y1)
            axs[1][1].set_aspect('equal')

            pyplot.show()

    if args.dist > 0:
        near_misses(logs, args.dist, start, args.tdelta)
    else:
        data = {'tdelta': args.tdelta, 'ids': ids, 'logs': logs}
        json.dump(data, args.outfile)
