output "main_queue_url" {
  description = "URL of the main SQS queue (use for SQS_QUEUE_URL)"
  value       = aws_sqs_queue.main.url
}

output "main_queue_arn" {
  value = aws_sqs_queue.main.arn
}

output "dlq_url" {
  description = "URL of the Dead Letter Queue (use for SQS_DLQ_URL)"
  value       = aws_sqs_queue.dlq.url
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "app_instance_public_ip" {
  description = "Public IP of the EC2 instance running the app"
  value       = aws_instance.app.public_ip
}

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)"
  value       = aws_db_instance.postgres.endpoint
}

output "rds_database_name" {
  description = "RDS PostgreSQL database name"
  value       = aws_db_instance.postgres.db_name
}
