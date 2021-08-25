import argparse
import csv
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
    v = (x[1:] - x[:-1]) / td
    v = np.append(v, v[-1])

    vs = filter(v, tavg / td)
    return vs

def check_igc(hdr, data):
    utc = data['utc']

    # Sample interval
    res = mode(utc[1:] - utc[:-1])
    delta_t = res.mode[0]

    # Check for >= 4s sampling
    if delta_t > 4:
        logging.warn("%s sample interval > 4s, %.1f", hdr['id'], delta_t)
        return False

    return True

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
    xdelta = xw[1:] - xw[:-1]
    ydelta = yw[1:] - yw[:-1]
    heading = np.degrees(np.arctan2(xdelta, ydelta))
    heading = np.append(heading, heading[-1])

    unwrapped_heading = np.unwrap(np.radians(heading))
    av_unwrapped_heading = filter(unwrapped_heading, 4 / tdelta)

    # Calculate speed
    speed = np.sqrt(xdelta ** 2  + ydelta ** 2) / tdelta
    speed = np.append(speed, speed[-1])
    speed = filter(speed, 5 / tdelta)

    # Bank angle
    omega = (unwrapped_heading[1:] - unwrapped_heading[:-1]) / tdelta
    omega = np.append(omega, omega[-1])
    theta = np.degrees(np.arctan(omega * speed / 9.81))

    av_theta = filter(theta, 5 / tdelta)

    # Pitch angle
    zdelta = z[1:] - z[:-1]
    zdelta = np.append(zdelta, zdelta[-1])
    pitch = np.degrees(zdelta / (speed * tdelta))
    pitch = filter(pitch, 2 / tdelta)

    return xw, yw, np.mod(np.degrees(av_unwrapped_heading), 360), av_theta, pitch 

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
    transformer = Transformer.from_crs(EPSG_XY, EPSG_ECEF)
    xec, yec, zec = transformer.transform(y[n:m], x[n:m], z[n:m])

    # Calculate ECEF speed components
    vx = calc_speed(xec, tdelta, 5)
    vy = calc_speed(yec, tdelta, 5)
    vz = calc_speed(zec, tdelta, 5)

    # Rotate orientation from local to ECEF
    ori_arr = []
    for i in range(n, m):
        # Init
        attitude = Rotation.from_euler("zyx", [0, 0, 0], degrees=True).as_matrix()

        # Rotate to view
        rot = Rotation.from_euler("zyx", [-lon, lat, 0], degrees=True)
        attitude = rot.apply(attitude)

        # Set attitude
        rot = Rotation.from_euler("zyx", [0, 90, 0], degrees=True)
        attitude = rot.apply(attitude)

        rot = Rotation.from_euler("zyx", [-heading[i], -pitch[i], -roll[i]], degrees=True)
        attitude = rot.apply(attitude)

        # Convert to rotation vector
        ori = Rotation.from_matrix(attitude).as_rotvec()
        ori_arr.append(ori)

    out = np.array(ori_arr).transpose()
    return np.transpose(np.vstack((xec, yec, zec, vx, vy, vz, out[0], out[1], out[2])))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("outfile", type=argparse.FileType('wt'),
                        help="Output file")
    parser.add_argument('--igc', '-i', nargs='*',
                        type=argparse.FileType('r', errors=None),
                        help='IGC files with ellipsoid datum')
    parser.add_argument('--start', '-s', type=int,
                        help='UTC start time (format 130415)')
    parser.add_argument('--stop', '-e', type=int,
                        help='UTC end time (format 131030)')
    parser.add_argument('--wind_speed', '-w', type=float, default=0.0,
                        help='Wind speed (kts), default 0kts')
    parser.add_argument('--wind_dir', '-d', type=float, default=0.0,
                        help='Wind direction')
    parser.add_argument('--tdelta', '-t', type=float, default=0.1,
                        help='Output time sample (s), default 0.1s')
    parser.add_argument('--geoid', '-g', type=float, default=48.0,
                        help='Geoid height (m), default 48m')
    parser.add_argument('--diag', action='store_true',
                        help='Make diagnostic plots')
    args = parser.parse_args()

    # Time parameters
    start = parse_utc(args.start)
    stop = parse_utc(args.stop)

    for igc_file in args.igc:
        hdr, data = parse_igc(igc_file)

        if not check_igc(hdr, data):
            continue

        utc, lat, lon = data['utc'], data['lat'], data['lon']
        alt_p, alt_g = data['alt'], data['alt_gps']

        # IGC file sample interval
        res = mode(utc[1:] - utc[:-1])
        delta_t_igc = res.mode[0]

        # Fuse pressure and GPS altitudes
        alt = fuse_altitude(alt_p, alt_g, delta_t_igc)

        # Subtract Geoid height
        alt = alt - args.geoid

        # Interpolate and convert to local X/Y/Z coordinates
        t, x, y, z = xyz_resample(utc, lat, lon, alt, args.tdelta)

        # Calculate flight dynamics
        x1, y1, heading, roll, pitch = calc_dynamics(x, y, z, args.tdelta,
                args.wind_speed, args.wind_dir)

        # Get data for FGFS
        out = fgfs_data(lat.mean(), lon.mean(),
                start, stop, t, x, y, z, heading, roll, pitch)

        # Save to file
        writer = csv.writer(args.outfile)
        writer.writerows(out)

        # Plot diagnostics
        if args.diag:
            fix, axs = pyplot.subplots(2, 2)
            axs[0][0].plot(z)

            axs[0][1].plot(pitch)

            axs[1][0].plot(x, y)
            axs[1][0].set_aspect('equal')

            axs[1][1].plot(x1, y1)
            axs[1][1].set_aspect('equal')

            pyplot.show()
