SELECT * FROM snapshot 
INNER JOIN tiled_image ON snapshot.id = tiled_image.snapshot_id
INNER JOIN tile ON tiled_image.id = tile.tiled_image_id
INNER JOIN image_file_table ON image_file_table.id = tile.raw_image_oid
WHERE measurement_label = 'amiRNA_vis' AND 
time_stamp >= '1900-01-01' AND 
time_stamp < '2020-03-07 00:00:00' 