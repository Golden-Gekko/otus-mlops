from feast import Entity, FileSource


driver_entity = Entity(
    name='driver',
    description='Водитель такси',
    join_keys=['driver_id']
)

driver_stats_source = FileSource(
    name='driver_stats_source',
    path='data/driver_stats.parquet',
    timestamp_field='event_timestamp',
    # created_timestamp_column='created',
)
