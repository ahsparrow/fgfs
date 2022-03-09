# IGCVis

Utilites for using the Flightgear flight simulator to visualise IGC logs

## Basic usage

Download log files from SoaringSpot

    python scraper.py \
        https://www/soaringspot.com/en_gb/hus-bos-challenge-cup-international-2021-husbands-bosworth-2021/results/magenta/task-1-on-2021-08-07 logs

Find some near misses (closer than 30m)

    python prox.py 154 30 logs/*

Generate flight file

    python fgfs.py --file data.json --start 131800 --duration 120 \
        --wind_speed 9 --wind_direction 43 154 logs/*

Replay to FGFS (showing aircraft within 300m of HOY)

    python gui.py --dist 300 HOY data.json

## Flightgear config

Run Flightgear with

    ./FlightGear-2020.3.11-x86_64.AppImage \
        --config=/home/ahs/src/fgfs/nas/config.xml --launcher
