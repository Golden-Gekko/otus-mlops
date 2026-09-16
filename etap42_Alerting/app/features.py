from pyspark.sql import DataFrame
from pyspark.sql.functions import coalesce, col, dayofweek, lit, month, to_timestamp
from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

INPUT_SCHEMA = StructType(
    [
        StructField('transaction_id', LongType(), True),
        StructField('tx_datetime', StringType(), True),
        StructField('customer_id', LongType(), True),
        StructField('terminal_id', LongType(), True),
        StructField('tx_amount', DoubleType(), True),
        StructField('tx_time_seconds', LongType(), True),
        StructField('tx_time_days', LongType(), True),
    ]
)

MODEL_FEATURE_COLS = [
    'customer_id',
    'tx_amount',
    'tx_time_days',
    'terminal_id',
    'day_of_week',
    'month',
]


def prepare_features(df: DataFrame) -> DataFrame:
    ts = to_timestamp(col('tx_datetime'), 'yyyy-MM-dd HH:mm:ss')
    day = coalesce(
        dayofweek(ts),
        ((col('tx_time_days') % 7) + 1).cast('int'),
        lit(1),
    )
    month_col = coalesce(month(ts), lit(1))
    return df.withColumn('day_of_week', day).withColumn('month', month_col)
