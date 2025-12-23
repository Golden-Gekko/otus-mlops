# Домашнее задание: Периодический запуск процедуры очистки датасета мошеннических финансовых транзакций

---

## Запуск

### 1. Подготовка

1. Установите [Terraform](https://developer.hashicorp.com/terraform/downloads)

2. Получите:
    - **OAuth-токен**: [https://oauth.yandex.ru/authorize?response_type=token&client_id=1a699ffb0...](https://oauth.yandex.ru/authorize?response_type=token&client_id=1a699ffb0d8d4d3a92f0c0b5e5a1b3d7)
    - **Cloud ID** и **Folder ID**: в [консоли Yandex Cloud](https://console.cloud.yandex.ru/)

### 2. Настройка Terraform

1. Перейдите в папку с инфраструктурой:
    ```bash
    cd infra
    ```
2. Создайте файл `terraform.tfvars` на основе шаблона:
    ```bash
    cp terraform.tfvars.example terraform.tfvars
    ```
3. Заполните его своими данными:
    ```
    yc_config = {
    token     = "y0__..."  # ваш OAuth-токен
    cloud_id  = "b1g..."   # Cloud ID
    folder_id = "b1g..."   # Folder ID
    zone      = "ru-central1-a"
    }
    ...
    ```

### 3. Запуск инфраструктуры

```bash
terraform init
terraform apply
```

Дождитесь завершения. Terraform создаст:
- bucket с данными
- сеть и правила доступа
- кластер AirFlow

---

### 4. Запуск скриптов копирования

1. Перейдите в корневой каталог

```bash
cd ..
```

2. Установите пакетный менеджер `uv`, если ещё не установлен

```bash
pip install uv
```

3. Установите виртуальное окружение
```bash
uv sync

# Активация виртуального окружения
source .venv/bin/activate  # Linux/Mac
# или
.venv\Scripts\activate     # Windows
```

4. Запустите скрипт

```bash
cd scripts
```

**Основной синтаксис**:
```bash
python main.py [copy_limit] [--only {vars,dags,src,data}]
```
**Параметры**:

- `copy_limit` (опциональный):
  - `latest` - только последние данные (по умолчанию)
  - `all` - все данные
  - число - ограничение количества записей

- `--only` (опциональный):
  - `vars` - только переменные Airflow
  - `dags` - только DAG-файлы
  - `src` - только исходный код
  - `data` - только данные

**Примеры использования**:

- Копировать только последние данные:

```bash
python script.py
```

- Копировать все данные:

```bash
python script.py all
```

- Копировать только DAGs:

```bash
python script.py latest --only dags
```

---

### 5. Остановка (очиска) кластера

С целью предотвращения ошибок желательно предварительно очистить созданный бакет от данных вручную либо с помощью команды

```bash
aws s3 rm s3://<BUCKET_NAME> --recursive --endpoint-url https://storage.yandexcloud.net
```

Далее удалить созданную инфраструктуру

```bash
terraform destroy
```

---

## Скриншоты

### Наличие очищенного `.parquet` файла

![hdfs dfs -ls /user/ubuntu/data](screenshots/parquet.png)

