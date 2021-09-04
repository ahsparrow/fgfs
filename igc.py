import logging

import numpy as np
from pyproj import Transformer
from scipy.interpolate import splrep, splev

EPSG_WGS84 = 4326
EPSG_XY = 3035

def check(data):
    # Sample interval
    duration = data['utc'][-1] - data['utc'][0]
    delta = duration / (len(data['utc']) - 1)

    return round(delta)

# Apply simple running average
def boxcar(data, n):
    # Filter length must be odd
    n1 = int(n // 2) * 2 + 1

    kernel = np.ones(n1) / n1
    m = n1 // 2

    # Pad data to minimise end effects
    pad = np.ones(m)
    d = np.concatenate((pad * data[0], data, pad * data[-1]))

    out = np.convolve(d, kernel, mode='valid')
    return out

# Fuse GPS and pressure altitudes
def fuse_altitude(alt_pressure, alt_gps, delta_t):
    delta_alt = boxcar(alt_gps - alt_pressure, 60 / delta_t)
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

# Caculate speed from 1-D array of positions
def speed(x, td, tavg):
    v = np.diff(x, append=x[-1:]) / td
    vs = boxcar(v, tavg / td)
    return vs

def interpolate_xyz(hdr, data, tdelta_igc, tdelta, elevation, geoid):
    # Bug in some loggers - remove duplicate samples
    u, idx = np.unique(data['utc'], return_index=True)
    data = data[idx]

    utc, lat, lon = data['utc'], data['lat'], data['lon']
    alt_p, alt_g = data['alt'], data['alt_gps']

    # Fuse pressure and GPS altitudes
    alt = fuse_altitude(alt_p, alt_g, tdelta_igc)

    # Correct for geoid/ellipsoid altitude reference
    takeoff_alt = np.mean(alt_g[:10])

    err_geoid = abs(takeoff_alt - elevation)
    err_ellip = abs((takeoff_alt - geoid) - elevation)

    if (err_ellip < err_geoid):
        alt = alt - geoid

    min_err = min(err_ellip, err_geoid)
    if min_err > 10:
        logging.warning("Takeoff elevation error exceeds 10 m: %.1f m" % min_err)

    # Interpolate and convert to local X/Y/Z coordinates
    t, x, y, z = xyz_resample(utc, lat, lon, alt, tdelta)

    return t, x, y, z

# Calculate flight dynamics, heading, roll, etc.
def dynamics(x, y, z, tdelta, wind_speed, wind_dir):
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
    av_unwrapped_heading = boxcar(unwrapped_heading, 4 / tdelta)

    # Calculate speed
    speed = np.sqrt(xdelta ** 2  + ydelta ** 2) / tdelta
    speed = boxcar(speed, 5 / tdelta)

    # Bank angle
    omega = np.diff(unwrapped_heading, append=unwrapped_heading[-1:]) / tdelta
    theta = np.degrees(np.arctan(omega * speed / 9.81))

    av_theta = boxcar(theta, 5 / tdelta)

    # Pitch angle
    zdelta = np.diff(z, append=z[-1:])
    pitch = np.degrees(zdelta / (speed * tdelta))
    pitch = boxcar(pitch, 2 / tdelta)

    return xw, yw, np.mod(np.degrees(av_unwrapped_heading), 360), av_theta, pitch 

