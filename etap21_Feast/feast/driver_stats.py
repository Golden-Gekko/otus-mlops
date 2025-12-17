from datetime import timedelta

from feast import FeatureView, Field
from feast.types import Float32, Int32

from definitions import driver_entity, driver_stats_source


driver_stats_fv = FeatureView(
    name='driver_stats',
    entities=[driver_entity],
    ttl=timedelta(days=365),
    schema=[
        Field(name='conv_rate', dtype=Float32),
        Field(name='acc_rate', dtype=Float32),
        Field(name='avg_daily_trips', dtype=Int32),
    ],
    source=driver_stats_source,
    tags={'team': 'driver'}
)
