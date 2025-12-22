from pathlib import Path

from feast import Entity, FileSource

current_dir = Path(__file__).parent
data_path = (current_dir / 'data' / 'driver_stats.parquet').absolute()

driver_entity = Entity(
    name='driver',
    description='Водитель такси',
    join_keys=['driver_id']
)

driver_stats_source = FileSource(
    name='driver_stats_source',
    path=str(data_path),
    timestamp_field='event_timestamp',
)
