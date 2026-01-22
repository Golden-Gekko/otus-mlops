resource "random_id" "bucket_id" {
  byte_length = 8
}

# Бакет
resource "yandex_storage_bucket" "bucket" {
  bucket        = "${var.bucket_name}-${random_id.bucket_id.hex}"
  access_key    = var.access_key
  secret_key    = var.secret_key
  force_destroy = true

  # Публичный на чтение
  anonymous_access_flags {
    read = true
    list = true
  }
}