#! python

import psycopg2
import psycopg2.extras
import argparse
import json
import os
import sys
import zipfile
import paramiko
import numpy as np
import cv2
import datetime
from tqdm import tqdm

def options():
    parser = argparse.ArgumentParser(description='Retrieve data from a LemnaTec database.',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-c", "--config", help="JSON config file.", required=True)
    parser.add_argument("-e", "--exper", help="Experiment number/name (measurement label)", required=True)
    parser.add_argument("-l", "--camera", help="Camera label. VIS or PSII or NIR", required=False)
    parser.add_argument("-i", "--frameid", help="image frame # to download. Argument accepts multiple frames delimited by space.",
                        required=False, nargs='+')
    parser.add_argument("-o", "--outdir", help="Output directory for results.", required=True)
    parser.add_argument("-a", "--date1", help="Date for start of data series (YYYY-mm-dd).", required=False)
    parser.add_argument("-z", "--date2", help="Date for end of data series (YYYY-mm-dd) (exclusive).", required=False)
    parser.add_argument("-d", "--append", help="add new files to existing directory", required=False, action='store_true')
    args = parser.parse_args()

    # Try to make output directory, throw an error and quit if it already exists and append was not given.
    if os.path.exists(args.outdir) and not args.append:
        raise SystemExit("The directory \"{0}\" already exists! Use --append to download new images to \"{0}\"".format(args.outdir))
    else:
        os.makedirs(args.outdir, exist_ok=True)
        
    return args

def main():
    # Read user options
    args = options()
  
    # Read the database connetion configuration file
    config = open(args.config, 'r')
    
    # Load the JSON configuration data
    db = json.load(config)
    
    #Load the experiment number
    exp = args.exper

    # SSH connection
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(db['hostname'], username=db['username'], password=db['password'])
    sftp = ssh.open_sftp()

    # Generate time stamp (as a sequence) for csv file
    now = datetime.datetime.now()
    time = now.strftime("%Y%m%dT%H%M%S")

    # Create the SnapshotInfo csv file (with experiment and time information in file name)
    csv = open(os.path.join(args.outdir, args.exper+"_SnapshotInfo_"+time+".csv"), "w")

    # Connect to the LemnaTec database
    conn = psycopg2.connect(host=db['dbhostname'], user=db['dbusername'], password=db['dbpassword'], database=db['dbname'])
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # Load date range (if applicable)
    # 2 dates given
    if args.date1 is not None and args.date2 is not None:
        try:
            #check date format
            datetime.datetime.strptime(args.date1, '%Y-%m-%d')
            date_start = args.date1
            datetime.datetime.strptime(args.date2, '%Y-%m-%d')
            date_end = args.date2
        except ValueError as e:
            raise SystemExit(e.args[0])
        print("Preparing to download snapshots between " + date_start + " and " + date_end + "...")
    
    # only 1 date given
    elif (not (args.date1 is None and args.date2 is None)):
        raise SystemExit("Please enter both a valid start date (-a) and end date (-z) in the format YYYY-mm-DD.")
    
    # no date given
    else:
        print("Preparing to download all snapshots from measurement label {0}...".format(exp))
        date_start = '1900-01-01'
        date_end = now.strftime('%Y-%m-%d')
        date_end = datetime.datetime.strptime(date_end,'%Y-%m-%d') + datetime.timedelta(days=1)
    
    # Load Camera label   
    if args.camera is None:
        camera_label = '%' #if no camera label is passed then match any camera
    else:
        camera_label = args.camera+'%' #add wildcard to match number
    
    # Load frameid
    if args.frameid is None:
        frameid = tuple(range(1,100))# HOpefully this is enough to get all of them ?!
        # CAST(frame as CHAR) LIKE '%' -- use this to match as a character
    else: 
        frameid = tuple(args.frameid)  #-- str(args.frameid) to match a single value as a character with LIKE
        # frame IN   -- use this to match as a number
    
    # Create data dictionary for psqgl
    data = {'exp':exp, 'date_start':date_start, 'date_end':date_end, 'camera_label':camera_label, 'frameid':frameid}

    # Get all image metadata
    cur.execute("SELECT * FROM snapshot "
                "INNER JOIN tiled_image ON snapshot.id = tiled_image.snapshot_id "
                "INNER JOIN tile ON tiled_image.id = tile.tiled_image_id "
                "INNER JOIN image_file_table ON image_file_table.id = tile.raw_image_oid "
                "WHERE measurement_label = %(exp)s AND "
                "time_stamp >= %(date_start)s AND "
                "time_stamp <= %(date_end)s AND "
                "camera_label ILIKE %(camera_label)s AND "
                "frame IN %(frameid)s ",
                data)
    
    snapshots = cur.fetchall()
    
    # Create SnapshotInfo.csv file
    header = ['experiment', 'id', 'plant barcode', 'car tag', 'timestamp', 'weight before', 'weight after',
              'water amount', 'completed', 'measurement label', 'tag', 'image name']
    csv.write(','.join(map(str, header)) + '\n')

    # Stats
    total_snapshots = len(snapshots)
    print('{0} snapshots to download'.format(total_snapshots))

    for snapshot in tqdm(snapshots):
        
        # Read LemnaTec database time format for renaming output PNG files
        lt_time = snapshot['time_stamp'] #this is already in a date format. don't need to parse
        lt_time_neat = datetime.datetime.strftime(lt_time, '%Y%m%dT%H%M%S')
        image_name = '-'.join([snapshot['id_tag'], snapshot['measurement_label'],
                               lt_time_neat, snapshot['camera_label'], str(snapshot['frame'])])

        print('\n'+image_name)
        
        values = [exp, snapshot['id'], snapshot['id_tag'], snapshot['car_tag'],
                  snapshot['time_stamp'].strftime(
                      '%Y-%m-%d %H:%M:%S'), snapshot['weight_before'],
                  snapshot['weight_after'], snapshot['water_amount_g'], snapshot['propagated'],
                  snapshot['measurement_label'], '', image_name]

        csv.write(','.join(map(str, values)) + '\n')

        # Create the local directory
        snapshot_dir = args.outdir
        pimdir = os.path.join(snapshot_dir, 'pim')
        # don't redownload existing images
        if os.path.exists(os.path.join(snapshot_dir, image_name+'.png')) or os.path.exists(os.path.join(pimdir,image_name+'.pim')):
            print('...skipping, image file already exists!')
            continue
        else:
            os.makedirs(snapshot_dir, exist_ok=True)

            # Copy the raw image to the local directory
            remote_dir = os.path.join(db['path'],
                                      db['dbname'],
                                      snapshot['path'])
            local_file = os.path.join(snapshot_dir, "blob" + str(snapshot['raw_image_oid']))
            # Change file paths on Windows systems to unix style for unix server
            if sys.platform.startswith('win'):
                local_file = local_file.replace('\\', '/')
                remote_dir = remote_dir.replace('\\', '/')

            try:
                sftp.get(remote_dir, local_file)

            except IOError as e:
                print(
                    "I/O error({0}): {1}. Offending file: {2}".format(e.errno, e.strerror, remote_dir))

            # skip snapshot if dir already exists AND args.force is True
            # if args.force is false it shouldn't have made it this far. see options()
            if os.path.exists(local_file):
                # Is the file a zip file?
                if zipfile.is_zipfile(local_file):
                    zf = zipfile.ZipFile(local_file)
                    zff = zf.open("data")
                    img_str = zff.read()

                    if 'VIS' in snapshot['camera_label'].upper() or 'TV' in snapshot['camera_label'].upper():
                        # dataformat = 9 for 8 bit bayer mosaic. others?
                        if snapshot['dataformat'] == 9:    
                            if len(img_str) == db['vis_height'] * db['vis_width']:
                                raw = np.frombuffer(
                                    img_str, dtype=np.uint8, count=db['vis_height']*db['vis_width'])
                                raw_img = raw.reshape(
                                    (db['vis_height'], db['vis_width']))
                                img = cv2.cvtColor(raw_img, db['colour'])
                                rotate_flip_type = snapshot['rotate_flip_type']
                                # original flip type was 180 => flip_type = 2
                                img = rotate_image(img, rotate_flip_type)
                                cv2.imwrite(os.path.join(
                                    snapshot_dir, image_name + ".png"), img)
                            else:
                                print("Warning: File {0} containing image {1} seems corrupted.".format(local_file,
                                                                                                image_name))

                        else:
                            print("Warning: File {0} containing image {1} had a different data format than expected.".format(local_file,
                                                                                                                          image_name   ))
                    elif 'NIR' in snapshot['camera_label'].upper():
                        raw_rescale = None
                        if snapshot['dataformat'] == 4:
                            # New NIR camera data format (16-bit)
                            if len(img_str) == (db['nir_height'] * db['nir_width']) * 2:
                                raw = np.frombuffer(img_str, dtype=np.uint16,
                                                    count=db['nir_height'] * db['nir_width'])
                                if np.max(raw) > 4096:
                                    print(
                                        "Warning: max value for image {0} is greater than 4096.".format(image_name))
                                raw_rescale = np.multiply(raw, 16)
                            else:
                                print("Warning: File {0} containing image {1} seems corrupted.".format(local_file,
                                                                                                    image_name))
                        elif snapshot['dataformat'] == 0:
                            # Old NIR camera data format (8-bit)
                            if len(img_str) == (db['nir_height'] * db['nir_width']):
                                raw_rescale = np.frombuffer(img_str, dtype=np.uint8,
                                                            count=db['nir_height'] * db['nir_width'])
                            else:
                                print("Warning: File {0} containing image {1} seems corrupted.".format(local_file,
                                                                                                       image_name))
                        if raw_rescale is not None:
                            raw_img = raw_rescale.reshape(
                                (db['nir_height'], db['nir_width']))
                            rotate_flip_type = snapshot['rotate_flip_type']
                            raw_img = rotate_image(raw_img, rotate_flip_type)
                            cv2.imwrite(os.path.join(
                                snapshot_dir, image_name + ".png"), raw_img)
                            os.remove(local_file)

                    elif 'PSII' in snapshot['camera_label'].upper():

                        raw_rescale = None
                        # dataformat = 11 for the text file in frame 0 from Walz
                        if snapshot['dataformat'] == 4:
                            # camera data format (16-bit)
                            if len(img_str) == (db['psII_height'] * db['psII_width']) * 2:
                                raw = np.frombuffer(img_str, dtype=np.uint16,
                                                    count=db['psII_height'] * db['psII_width'])
                                if np.max(raw) > 4096:
                                    print(
                                        "Warning: max value for image {0} is greater than 4096.".format(image_name))
                                raw_rescale = np.multiply(raw, 16)
                            else:
                                print("Warning: File {0} containing image {1} seems corrupted.".format(local_file,
                                                                                                    image_name))
                        elif snapshot['dataformat'] == 0:
                            #  data format (8-bit)
                            if len(img_str) == (db['psII_height'] * db['psII_width']):
                                raw_rescale = np.frombuffer(img_str, dtype=np.uint8,
                                                            count=db['psII_height'] * db['psII_width'])
                            else:
                                print("Warning: File {0} containing image {1} seems corrupted.".format(local_file,
                                                                                                       image_name))
                        elif snapshot['dataformat'] == 100000:
                            # data format code for last frame which corresponds to the pim file
                            os.makedirs(pimdir, exist_ok=True)
                            # Pass "wb" to write a new file, or "ab" to append
                            with open(os.path.join(pimdir, image_name + ".pim"), "wb") as binary_file:
                                # Write text or bytes to the file
                                binary_file.write(img_str)
                        
                        if raw_rescale is not None:
                            raw_img = raw_rescale.reshape((db['psII_height'], db['psII_width']))
                            rotate_flip_type = snapshot['rotate_flip_type']
                            # original flip type was 180 => flip_type = 2
                            raw_img = rotate_image(raw_img, rotate_flip_type)
                            cv2.imwrite(os.path.join(
                                snapshot_dir, image_name + ".png"), raw_img)
        
                    zff.close()
                    zf.close()
                    try:
                        os.remove(local_file)
                    except OSError:
                        print("Error while deleting file")
                else:
                    print("Warning: the local file {0} containing image {1} is not a proper zip file.".format(
                        local_file, image_name))
            else:
                print("Warning: the local file {0} containing image {1} was not copied correctly.".format(
                    local_file, image_name))

    #Close everything
    cur.close()
    conn.close()
    sftp.close()
    ssh.close()

    #Print report
    print("\nTotal snapshots = " + str(total_snapshots))


def rotate_image(img, flip_type):
    """Rotate image based on flip code

    :param img: ndarray
    :param flip_type: int
    :return img: ndarray
    """
    if flip_type == 0:
        img = img
    elif flip_type == 1:
        img = cv2.rotate(img,cv2.ROTATE_90_CLOCKWISE)
    elif flip_type == 2:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif flip_type == 3:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif flip_type == 4:
        # flip around y axis
        img = cv2.flip(img, 1)
    elif flip_type == 5:
        img = cv2.flip(img, 1)
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif flip_type == 6:
        # flip around x axis
        img = cv2.flip(img, 0)
    elif flip_type == 7:
        img = cv2.flip(img, 0)
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return img

if __name__ == '__main__':
    main()
