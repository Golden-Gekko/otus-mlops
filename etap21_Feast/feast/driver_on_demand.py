
from feast import Field
from feast.types import Float64
from feast.on_demand_feature_view import on_demand_feature_view
import pandas as pd

from driver_stats import driver_stats_fv


@on_demand_feature_view(
    sources=[driver_stats_fv],
    schema=[Field(name='activity_score', dtype=Float64)]
)
def activity_score(features_df: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame()
    # Просто какая-то формула, т.к. не нашел описания датасета :)
    df['activity_score'] = (
        features_df['conv_rate'] ** 2
        + features_df['acc_rate']
        * features_df['avg_daily_trips'].mean()
        / features_df['avg_daily_trips']
    )
    return df
