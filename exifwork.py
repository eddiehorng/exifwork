#!/usr/bin/python3
import os, sys, datetime, subprocess, argparse, logging
#exiftool -P -MPF:ALL= -o /sync2google/test/2022-02-01/ /moments/ipad/2022-02-01
script_dir = os.path.abspath(os.path.dirname(__file__))


src_root_dir = '/photos/ipad'
dst_root_dir = '/sync2google/ipad'

logger = logging.getLogger()

DRY_RUN = False


def exif_mod():
    def format_exiftools_errmsg(msg):
        lines = msg.decode().split('\n')
        return '\n'.join(lines[-5:])

    d_src = datetime.date.today() - datetime.timedelta(days=1)
    str_month = d_src.strftime('%Y/%m')
    src_dir = os.path.join(src_root_dir, str_month)
    dst_dir = os.path.join(dst_root_dir, str_month)
    logger.info('target date {}, {} => {}'.format(d_src, src_dir, dst_dir))
    if os.path.exists(src_dir):
        cmd = 'exiftool -P -MPF:ALL= -o {}/ {}'.format(dst_dir, src_dir)
        if DRY_RUN:
            logger.info('[DRYRUN] {}'.format(cmd))
        else:
            try:
                output = subprocess.check_output(cmd, shell=True)
            except subprocess.CalledProcessError as e:
                output = e.output
            logger.info('{}\n{}'.format(cmd, format_exiftools_errmsg(output)))


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
