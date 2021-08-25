import json
import socket
import sys
import time
import xdrlib

import numpy as np

#----------------------------------------------------------------------

def send_msg(port, id, x, y, z, orix, oriy, oriz, vx, vy, vz):
    model = b'Aircraft/DG-101G/Models/DG-101G.xml'
    model += bytearray(96 - len(model))

    # Not sure what value this should be, but less than this gives jerky
    # playback
    lag = 0.05

    # Pack XDR data
    packer = xdrlib.Packer()

    utc_secs = time.time() % (24 * 3600)
    packer.pack_double(utc_secs)
    packer.pack_double(lag)

    packer.pack_double(x)
    packer.pack_double(y)
    packer.pack_double(z)

    packer.pack_float(orix)
    packer.pack_float(oriy)
    packer.pack_float(oriz)

    packer.pack_float(vx)
    packer.pack_float(vy)
    packer.pack_float(vz)

    # Angular velocity
    packer.pack_float(0)
    packer.pack_float(0)
    packer.pack_float(0)

    # Linear acceleration
    packer.pack_float(0)
    packer.pack_float(0)
    packer.pack_float(0)

    # Angular acceleration
    packer.pack_float(0)
    packer.pack_float(0)
    packer.pack_float(0)

    data = model + packer.get_buffer() + bytearray(4)

    # Make header
    idb = bytes(id[:8], 'ascii')
    hdr = b"FGFS" + \
          bytearray([0, 1, 0, 1]) +\
          bytearray([0, 0, 0, 7]) +\
          bytearray([0, 0, 0, len(data)+32]) +\
          bytearray([0, 0, 0, 0]) +\
          bytearray([0, 0, 0, 0]) +\
          idb + bytearray(8 - len(idb))

    msg = hdr + data

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(msg, ("127.0.0.1", port))

# Calculate minimum distance between two logs
def min_distance(data1, data2):
    xyz1 = np.array([(x[0], x[1], x[2]) for x in data1])
    xyz2 = np.array([(x[0], x[1], x[2]) for x in data2])

    dist = np.linalg.norm(xyz1 - xyz2, axis=1)
    return np.min(dist)

# Replay log data
def replay(id, logs, tdelta, dist, port):
    # Find log data
    ref_log = None
    for log in logs:
        if log['id'] == id:
            ref_log = log
            break

    if ref_log is None:
        print("Can't find log for " + id)
        sys.exit()

    replay_logs = [ref_log]

    # Find close encounters
    for log in logs:
        log_id = log['id']
        if log_id != id:
            mdist = min_distance(ref_log['data'], log['data'])
            if mdist <= dist:
                print("Adding log " + log_id + ", min distance %d" % mdist)
                replay_logs.append(log)

    # Send data to FG sim
    for i in range(len(ref_log['data'])):
        for log in replay_logs:
            x, y, z, orix, oriy, oriz, vx, vy, vz = log['data'][i]
            send_msg(port, log['id'], x, y, z, orix, oriy, oriz, vx, vy, vz)

        time.sleep(tdelta)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=argparse.FileType('r'),
            help='JSON data file')
    parser.add_argument('id', nargs='?', help='id to replay')
    parser.add_argument('--dist', '-d', type=int, default=0,
            help='add if within distance (m)')
    parser.add_argument('--port', '-p', type=int, default=5124,
            help='FG port number')
    parser.add_argument('--list', '-l', action='store_true',
            help='print list of IDs in file')

    args = parser.parse_args()

    data = json.load(args.file)
    if args.list:
        print(", ".join(data['ids']))
        sys.exit(0)

    replay(args.id, data['logs'], data['tdelta'], args.dist, args.port)
