import sys

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, mean, stddev, row_number
from pyspark.sql.window import Window


def clean_data_pipeline(input_txt: str, output_parquet: str):
    print('Инициализация сессии')
    spark = SparkSession.builder.getOrCreate()

    print('Загрузка данных')
    df = (
        spark.read.option('header', 'false')
        .option('inferSchema', 'true')
        .option('comment', '#')
        .csv(input_txt)
        .toDF(
            'transaction_id',
            'tx_datetime',
            'customer_id',
            'terminal_id',
            'tx_amount',
            'tx_time_seconds',
            'tx_time_days',
            'tx_fraud',
            'tx_fraud_scenario',
        )
    )

    print('Удаление NaN')
    df = df.dropna()

    print('Удаление явных дубликатов')
    df = df.dropDuplicates()

    print('Удаление дубликатов по \'transaction_id\'')
    df = df.withColumn(
        'rn',
        row_number().over(
            Window.partitionBy('transaction_id')
            .orderBy('tx_datetime')
        )
    ).filter(col('rn') == 1).drop('rn')

    print('Фильтрация \'tx_amount > 0\'')
    df = df.filter(col('tx_amount') > 0)

    print('Удаление выбросов в \'tx_amount\' (три сигма)')
    stats = df.select(
        mean('tx_amount').alias('m'),
        stddev('tx_amount').alias('s')
    ).first()
    if stats['s']:
        lower = stats['m'] - 3 * stats['s']
        upper = stats['m'] + 3 * stats['s']
        df = df.filter(
            (col('tx_amount') >= lower) & (col('tx_amount') <= upper)
        )

    print('Фильтр \'customer_id > 0\'')
    df = df.filter(col('customer_id') > 0)

    print('Сохранение')
    df.write.mode('overwrite').parquet(output_parquet)

    spark.stop()


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        print('Использование:')
        print('  python script.py <input_txt>')
        print('  python script.py <input_txt> <output_parquet>')
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = (
        sys.argv[2] if len(sys.argv) == 3 else input_path + '.parquet')

    clean_data_pipeline(input_path, output_path)
