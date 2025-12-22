# Feast Feature Store: Практическое задание

## Цель работы

Получить опыт работы с Feast, попрактиковаться в создании Feature View. В данном домашнем задании Вы познакомитесь с возможностями платформы управления признаками (Feature Store) Feast, научитесь создавать различные типы Feature Views и работать с ними на практике.

## Запуск проекта

### Настройка виртуального окружения с `uv`

```bash
# Инициализация окружения
uv sync

# Активация окружения
# На Windows:
.venv\Scripts\activate
# На Linux/Mac:
source .venv/bin/activate
```

### Развертывание Feast

```bash
cd feast
# Очистка
rm -rf data/registry.db data/online_store.db
# Инициализация
feast apply
```

### 3. Материализация признаков

```bash
feast materialize 2023-01-01T00:00:00 2025-12-31T23:59:59
```


### Запуск и выполнение ноутбука

```bash
cd ..
jupyter notebook feast_test.ipynb
```
