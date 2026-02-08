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
