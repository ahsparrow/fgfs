import csv
import socket
import time
import xdrlib

#----------------------------------------------------------------------

def send(x, y, z, orix, oriy, oriz):
    model = b'Aircraft/DG-101G/Models/DG-101G.xml'
    model += bytearray(96 - len(model))

    velx = 0
    vely = 0
    velz = 0

    av1 = 0
    av2 = 0
    av3 = 0

    la1 = 0
    la2 = 0
    la3 = 0

    aa1 = 0
    aa2 = 0
    aa3 = 0

    packer = xdrlib.Packer()

    utc_secs = time.time() % (24 * 3600)
    packer.pack_double(utc_secs)
    lag = 0
    packer.pack_double(lag)

    packer.pack_double(x)
    packer.pack_double(y)
    packer.pack_double(z)

    packer.pack_float(orix)
    packer.pack_float(oriy)
    packer.pack_float(oriz)

    packer.pack_float(velx)
    packer.pack_float(vely)
    packer.pack_float(velz)

    packer.pack_float(av1)
    packer.pack_float(av2)
    packer.pack_float(av3)

    packer.pack_float(la1)
    packer.pack_float(la2)
    packer.pack_float(la3)

    packer.pack_float(aa1)
    packer.pack_float(aa2)
    packer.pack_float(aa3)

    data = model + packer.get_buffer() + bytearray(4)

    hdr = b"FGFS" + \
          bytearray([0, 1, 0, 1]) +\
          bytearray([0, 0, 0, 7]) +\
          bytearray([0, 0, 0, len(data)+32]) +\
          bytearray([0, 0, 0, 0]) +\
          bytearray([0, 0, 0, 0]) +\
          b"G-CHOY" + bytearray(2)

    msg = hdr + data

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(msg, ("127.0.0.1", 5124))

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("infile", type=argparse.FileType("r"))

    args = parser.parse_args()

    reader = csv.reader(args.infile)
    for x in reader:
        x, y, z, orix, oriy, oriz = map(float, x)

        send(x, y, z, orix, oriy, oriz)
        time.sleep(0.1)
