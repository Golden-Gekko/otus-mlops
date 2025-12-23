import sys
import argparse

from upload_airflow_vars import upload_airflow_variables
from upload_dags import upload_dags
from upload_src import upload_src
from copy_external_data import copy_external_data


def main(copy_limit='latest', only=None):
    print('Запуск деплоя Airflow-инфраструктуры...')

    try:
        run_vars = only is None or only == 'vars'
        run_dags = only is None or only == 'dags'
        run_src = only is None or only == 'src'
        run_data = only is None or only == 'data'

        step = 1
        total_steps = sum([run_vars, run_dags, run_src, run_data])

        if run_vars:
            print(f'\n[{step}/{total_steps}] Загрузка переменных в Airflow...')
            upload_airflow_variables()
            step += 1

        if run_dags:
            print(f'\n[{step}/{total_steps}] Загрузка DAG-файлов...')
            upload_dags()
            step += 1

        if run_src:
            print(f'\n[{step}/{total_steps}] Загрузка исходного кода...')
            upload_src()
            step += 1

        if run_data:
            print(f'\n[{step}/{total_steps}] Копирование внешних данных...')
            copy_external_data(copy_limit=copy_limit)
            step += 1

        if total_steps == 4:
            print('\nДеплой завершён!')

    except Exception as e:
        print(f'\nОшибка: {e}')
        sys.exit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Деплой Airflow-инфраструктуры')
    parser.add_argument(
        'copy_limit',
        nargs='?',
        default='latest',
        help='Лимит копирования данных: "all", "latest" или число')
    parser.add_argument(
        '--only',
        choices=['vars', 'dags', 'src', 'data'],
        help='Запустить только указанную часть: vars, dags, src, data')

    args = parser.parse_args()
    main(copy_limit=args.copy_limit, only=args.only)
