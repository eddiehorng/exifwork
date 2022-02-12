#!/usr/bin/python3
import os, sys, datetime, subprocess, argparse, logging
#exiftool -P -MPF:ALL= -o /sync2google/test/2022-02-01/ /moments/ipad/2022-02-01
script_dir = os.path.abspath(os.path.dirname(__file__))

# date_until = datetime.date(2021, 6, 1)
date_until = None
src_root_dir = '/moments/ipad'
dst_root_dir = '/sync2google/ipad'

logger = logging.getLogger()

DRY_RUN = False

last_done_file = os.path.join(script_dir, 'lastdone.log')


def get_last_done():
    done_str = open(last_done_file).read().strip()
    return datetime.datetime.strptime(done_str, '%Y-%m-%d').date()


def update_last_done(d):
    with open(last_done_file, 'w') as fp:
        fp.write(str(d))


def exif_mod():
    d_since = get_last_done() + datetime.timedelta(days=1)
    d_until = date_until or datetime.date.today() - datetime.timedelta(days=1)
    logger.info('date range {} {}'.format(d_since, d_until))
    d = d_since
    while d <= d_until:
        src_dir = os.path.join(src_root_dir, str(d))
        if os.path.exists(src_dir):
            dst_dir = os.path.join(dst_root_dir, os.path.basename(src_dir))
            cmd = 'exiftool -P -MPF:ALL= -o {}/ {}'.format(dst_dir, src_dir)
            if DRY_RUN:
                logger.info('[DRYRUN] {}'.format(cmd))
            else:
                try:
                    output = subprocess.check_output(cmd, shell=True)
                    logger.info('{}\n{}'.format(cmd, output.decode()))
                    update_last_done(d)
                except subprocess.CalledProcessError as e:
                    logger.warning('{}\nerror:\n{}'.format(cmd, e.output.decode()))
        d = d + datetime.timedelta(days=1)


def setup_logger():
    global logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(os.path.join(script_dir, 'exif.log'))
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stdout_handler)


def main():
    global DRY_RUN
    setup_logger()
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--dryrun', action='store_true')
    args = parser.parse_args()

    DRY_RUN = args.dryrun
    exif_mod()


if __name__ == '__main__':
    main()
