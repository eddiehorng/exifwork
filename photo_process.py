#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import shutil
import subprocess
import configparser
import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Supported extensions
IMAGE_EXTENSIONS = {'.jpg', '.jpeg'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'}

# Global dryrun setting
DRY_RUN = False

def strip_mpf_from_jpeg(input_bytes: bytes) -> bytes:
    """
    Strips APP2 markers containing the Multi-Picture Format (MPF) signature
    and removes any trailing data after the End of Image (EOI) marker.
    """
    if not input_bytes.startswith(b'\xff\xd8'):
        raise ValueError("Not a valid JPEG image (missing SOI)")
        
    output = bytearray(b'\xff\xd8')
    i = 2
    n = len(input_bytes)
    
    while i < n:
        if i + 1 >= n:
            output.extend(input_bytes[i:])
            break
            
        if input_bytes[i] != 0xff:
            output.append(input_bytes[i])
            i += 1
            continue
            
        marker = input_bytes[i:i+2]
        
        if marker == b'\xff\xd8':
            output.extend(marker)
            i += 2
            continue
            
        if marker == b'\xff\xd9':
            output.extend(marker)
            # Truncate any trailer data after the first EOI marker
            break
            
        # Standalone markers with no length (TEM and RST0-RST7)
        if marker == b'\xff\x01' or (b'\xff\xd0' <= marker <= b'\xff\xd7'):
            output.extend(marker)
            i += 2
            continue
            
        # Markers with length
        if i + 3 >= n:
            output.extend(input_bytes[i:])
            break
            
        length = int.from_bytes(input_bytes[i+2:i+4], byteorder='big')
        
        # Check for APP2 (FF E2)
        if marker == b'\xff\xe2':
            # Check if it has the MPF signature: "MPF\0"
            if i + 4 + 4 <= n and input_bytes[i+4:i+8] == b'MPF\x00':
                # Skip the entire APP2 segment
                i += 2 + length
                continue
                
        # SOS (Start of Scan) starts the entropy-coded scan data
        if marker == b'\xff\xda':
            output.extend(input_bytes[i : i + 2 + length])
            i += 2 + length
            
            # Read until EOI, skipping stuffed FF bytes (FF 00) and RST markers
            while i < n:
                if i + 1 >= n:
                    output.extend(input_bytes[i:])
                    i = n
                    break
                if input_bytes[i] == 0xff:
                    next_byte = input_bytes[i+1]
                    if next_byte == 0xd9:
                        output.extend(b'\xff\xd9')
                        i += 2
                        return bytes(output)
                    elif next_byte == 0x00 or (0xd0 <= next_byte <= 0xd7):
                        output.extend(input_bytes[i:i+2])
                        i += 2
                    else:
                        output.extend(input_bytes[i:i+2])
                        i += 2
                else:
                    output.append(input_bytes[i])
                    i += 1
            continue
            
        output.extend(input_bytes[i : i + 2 + length])
        i += 2 + length
        
    return bytes(output)

def get_mov_resolution(filepath):
    """
    Parses a MOV/MP4 file to extract its video resolution (width and height)
    by reading track header (tkhd) structures.
    """
    with open(filepath, 'rb') as f:
        f.seek(0, 2)
        filesize = f.tell()
        f.seek(0)
        
        def read_atom(offset, size_limit):
            f.seek(offset)
            pos = offset
            while pos < offset + size_limit:
                f.seek(pos)
                header = f.read(8)
                if len(header) < 8:
                    break
                size = int.from_bytes(header[0:4], 'big')
                atom_type = header[4:8]
                
                header_size = 8
                if size == 1:
                    ext_size_bytes = f.read(8)
                    if len(ext_size_bytes) < 8:
                        break
                    size = int.from_bytes(ext_size_bytes, 'big')
                    header_size = 16
                elif size == 0:
                    size = filesize - pos
                
                payload_offset = pos + header_size
                payload_size = size - header_size
                
                if atom_type in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
                    res = read_atom(payload_offset, payload_size)
                    if res:
                        return res
                elif atom_type == b'tkhd':
                    f.seek(payload_offset)
                    version = f.read(1)[0]
                    
                    if version == 1:
                        # Skip flags (3), creation_time (8), modification_time (8), track_ID (4), reserved (4), duration (8) = 35 bytes
                        f.seek(payload_offset + 1 + 3 + 8 + 8 + 4 + 4 + 8)
                    else:
                        # Skip flags (3), creation_time (4), modification_time (4), track_ID (4), reserved (4), duration (4) = 23 bytes
                        f.seek(payload_offset + 1 + 3 + 4 + 4 + 4 + 4 + 4)
                        
                    # Skip reserved (8), layer (2), alternate_group (2), volume (2), reserved (2), matrix (36) = 52 bytes
                    f.seek(52, 1)
                    
                    w_bytes = f.read(4)
                    h_bytes = f.read(4)
                    if len(w_bytes) == 4 and len(h_bytes) == 4:
                        width = int.from_bytes(w_bytes[0:2], 'big')
                        height = int.from_bytes(h_bytes[0:2], 'big')
                        if width > 0 and height > 0:
                            return width, height
                            
                pos += size
            return None
            
        return read_atom(0, filesize)

def process_image(src_path, dest_dir):
    filename = os.path.basename(src_path)
    dest_path = os.path.join(dest_dir, filename)
    ext = os.path.splitext(filename)[1].lower()

    if DRY_RUN:
        if ext in {'.jpg', '.jpeg'}:
            logger.info(f"[DRYRUN] Would strip MPF from JPEG: {src_path} -> {dest_path}")
        else:
            logger.info(f"[DRYRUN] Would copy image: {src_path} -> {dest_path}")
        return

    if ext in {'.jpg', '.jpeg'}:
        logger.info(f"Stripping MPF from JPEG: {src_path} -> {dest_path}")
        try:
            with open(src_path, 'rb') as f:
                data = f.read()
            stripped_data = strip_mpf_from_jpeg(data)
            with open(dest_path, 'wb') as f:
                f.write(stripped_data)
        except Exception as e:
            logger.error(f"Failed to strip MPF from {src_path}, copying original file instead: {e}")
            try:
                shutil.copy2(src_path, dest_path)
            except Exception as copy_err:
                logger.error(f"Failed to copy original file: {copy_err}")
    else:
        logger.info(f"Copying image: {src_path} -> {dest_path}")
        try:
            shutil.copy2(src_path, dest_path)
        except Exception as e:
            logger.error(f"Failed to copy image {src_path}: {e}")

def process_video(src_path, dest_dir):
    filename = os.path.basename(src_path)
    dest_path = os.path.join(dest_dir, filename)
    
    if DRY_RUN:
        logger.info(f"[DRYRUN] Would check resolution and conditionally convert or copy video: {src_path} -> {dest_path}")
        return
        
    # Get MOV/MP4 resolution
    try:
        res = get_mov_resolution(src_path)
    except Exception as e:
        logger.error(f"Failed to parse video resolution for {src_path}: {e}")
        res = None

    if res:
        width, height = res
        logger.info(f"Video {filename} resolution: {width}x{height}")
        
        # Calculate FHD dimensions if larger than FHD
        is_landscape = width >= height
        max_w = 1920 if is_landscape else 1080
        max_h = 1080 if is_landscape else 1920
        
        if width > max_w or height > max_h:
            # Scale down preserving aspect ratio
            ratio = min(max_w / width, max_h / height)
            new_w = int(width * ratio)
            new_h = int(height * ratio)
            
            # Ensure even dimensions (required by libx264/yuv420p)
            new_w = (new_w // 2) * 2
            new_h = (new_h // 2) * 2
            
            logger.info(f"Converting video {filename} to FHD: {width}x{height} -> {new_w}x{new_h}")
            try:
                import imageio_ffmpeg
                ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:
                ffmpeg_bin = "ffmpeg"
                
            cmd = [
                ffmpeg_bin,
                "-i", src_path,
                "-vf", f"scale={new_w}:{new_h}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                dest_path,
                "-y"
            ]
            
            try:
                # Run ffmpeg command. Capture stderr for logging/debugging.
                result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                logger.info(f"Successfully converted and saved: {dest_path}")
                return
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode(errors='replace') if e.stderr else str(e)
                logger.error(f"Failed to convert video {filename} using ffmpeg. Command: {' '.join(cmd)}. Error: {err_msg}")
                # Fallback to copy original
                logger.info(f"Copying original video instead as fallback: {src_path} -> {dest_path}")
            except Exception as e:
                logger.error(f"Unexpected error converting video {filename}: {e}")
                logger.info(f"Copying original video instead as fallback: {src_path} -> {dest_path}")
        else:
            logger.info(f"Video {filename} is within FHD limits. Copying original.")
    else:
        logger.warning(f"Could not parse resolution for {filename}. Copying original as fallback.")

    # Fallback: Copy original video file
    try:
        shutil.copy2(src_path, dest_path)
        logger.info(f"Copied video: {src_path} -> {dest_path}")
    except Exception as e:
        logger.error(f"Failed to copy video {src_path}: {e}")

def main():
    global DRY_RUN
    parser = argparse.ArgumentParser(description="Process images and videos based on config.ini settings.")
    parser.add_argument("-c", "--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini"),
                        help="Path to the config.ini file (default: config.ini in script directory)")
    parser.add_argument("-d", "--dryrun", action="store_true", help="Enable dryrun mode (no reads or writes performed)")
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)
    if not os.path.isfile(config_path):
        logger.error(f"Config file not found at: {config_path}")
        sys.exit(1)

    logger.info(f"Loading configuration from: {config_path}")
    config = configparser.ConfigParser()
    config.read(config_path)

    if not config.has_section('settings'):
        logger.error("Config file missing [settings] section.")
        sys.exit(1)

    # Check for dryrun mode in CLI args
    DRY_RUN = args.dryrun
    if DRY_RUN:
        logger.info("DRYRUN MODE ENABLED - No files will be read, written, or directories created.")

    # 1. Parse source_dirs
    source_dirs_str = config.get('settings', 'source_dirs', fallback='')
    source_dirs = [d.strip() for d in source_dirs_str.split(',') if d.strip()]
    if not source_dirs:
        logger.error("No source directories defined in source_dirs.")
        sys.exit(1)

    # 2. Parse target_dir
    target_dir = config.get('settings', 'target_dir', fallback='').strip()
    if not target_dir:
        logger.error("No target directory defined in target_dir.")
        sys.exit(1)
    target_dir = os.path.abspath(target_dir)

    # 3. Parse ignore_before
    ignore_before_str = config.get('settings', 'ignore_before', fallback='').strip()
    ignore_date = None
    if ignore_before_str:
        try:
            ignore_date = datetime.datetime.strptime(ignore_before_str, '%Y-%m-%d').date()
            logger.info(f"Ignoring files modified before: {ignore_date}")
        except ValueError:
            logger.error(f"Invalid date format for ignore_before: {ignore_before_str}. Use YYYY-MM-DD.")
            sys.exit(1)

    # Process all source dirs
    max_processed_date = None  # track latest file date across all processed files
    for src_dir in source_dirs:
        src_dir = os.path.abspath(src_dir)
        if not os.path.isdir(src_dir):
            logger.warning(f"Source directory does not exist or is not a directory: {src_dir}. Skipping.")
            continue

        logger.info(f"Scanning source directory: {src_dir}")
        count_processed = 0
        count_too_old = 0
        count_wrong_type = 0

        all_files = []
        for dirpath, dirnames, filenames in os.walk(src_dir):
            for filename in filenames:
                all_files.append(os.path.join(dirpath, filename))
        logger.info(f"Found {len(all_files)} file(s) recursively in {src_dir}")

        for full_path in all_files:
            filename = os.path.basename(full_path)
            # Check modification time
            try:
                mtime = os.path.getmtime(full_path)
                file_date = datetime.date.fromtimestamp(mtime)
            except Exception as e:
                logger.error(f"Failed to get mtime for {filename}: {e}")
                continue

            if ignore_date and file_date < ignore_date:
                if DRY_RUN:
                    logger.info(f"Ignoring {filename} (modified {file_date} is before {ignore_date})")
                count_too_old += 1
                continue

            ext = os.path.splitext(filename)[1].lower()
            if ext not in IMAGE_EXTENSIONS and ext not in VIDEO_EXTENSIONS:
                if DRY_RUN:
                    logger.info(f"Skipping unsupported file type: {filename}")
                count_wrong_type += 1
                continue

            # Target subdir: [target-dir]/YYYY-MM-DD
            date_str = file_date.strftime('%Y-%m-%d')
            dest_subdir = os.path.join(target_dir, date_str)

            # Ensure destination subdirectory exists
            if not os.path.exists(dest_subdir):
                if DRY_RUN:
                    logger.info(f"[DRYRUN] Would create target subdirectory: {dest_subdir}")
                else:
                    try:
                        os.makedirs(dest_subdir)
                    except Exception as e:
                        logger.error(f"Failed to create target subdirectory {dest_subdir}: {e}")
                        continue

            if ext in IMAGE_EXTENSIONS:
                process_image(full_path, dest_subdir)
                count_processed += 1
                if not DRY_RUN and (max_processed_date is None or file_date > max_processed_date):
                    max_processed_date = file_date
            elif ext in VIDEO_EXTENSIONS:
                process_video(full_path, dest_subdir)
                count_processed += 1
                if not DRY_RUN and (max_processed_date is None or file_date > max_processed_date):
                    max_processed_date = file_date

        logger.info(f"Done with {src_dir}: {count_processed} processed, {count_too_old} skipped (too old), {count_wrong_type} skipped (unsupported type)")

    # Update ignore_before in config.ini to the day after the latest processed file date
    if not DRY_RUN and max_processed_date is not None:
        new_ignore_before = (max_processed_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        config.set('settings', 'ignore_before', new_ignore_before)
        try:
            with open(config_path, 'w') as f:
                config.write(f)
            logger.info(f"Updated ignore_before in config to: {new_ignore_before}")
        except Exception as e:
            logger.error(f"Failed to update ignore_before in config: {e}")

if __name__ == "__main__":
    main()
