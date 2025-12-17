from datetime import timedelta

from feast import Field, FeatureView
from feast.types import UnixTimestamp

from definitions import driver_entity, driver_stats_source


driver_activity_fv = FeatureView(
    name='driver_activity',
    entities=[driver_entity],
    ttl=timedelta(days=30),
    schema=[
        Field(name='event_timestamp', dtype=UnixTimestamp),
        Field(name='created', dtype=UnixTimestamp),
    ],
    source=driver_stats_source,
    tags={'team': 'driver'},
)
