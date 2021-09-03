## Basic usage

Load log files from SoaringSpot

    python scraper.py \
        hus-bos-challenge-cup-international-2021-husbands-bosworth-2021 \
        magenta/task-1-on-2021-08-07 logs

Find some near misses

    python fgfs.py data.json logs/* \
        --elev 188 --start 121500 --stop 151500 -w 9 -d 43 --dist=30

Generate flight file

    python fgfs.py data.json logs/*
        --elev 188 --start 131800 --stop 132000 -w 9 -d 43

Replay to FGFS (showing aircraft within 300m of HOY)

    python gui.py data.json HOY --dist 300

## Flightgear config

Run Flightgear with

    ./FlightGear-2020.3.11-x86_64.AppImage \
        --config=/home/ahs/src/fgfs/nas/config.xml --launcher
