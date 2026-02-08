variable "aws_region" {
  description = "AWS region for SQS queues"
  type        = string
  default     = "ap-south-1"
}

variable "queue_name" {
  description = "Name of the main ingestion queue (DLQ will be <name>-dlq)"
  type        = string
  default     = "ingestion-events"
}

variable "visibility_timeout_seconds" {
  description = "SQS visibility timeout (seconds) before message reappears after no delete"
  type        = number
  default     = 60
}

variable "max_receive_count" {
  description = "After this many receives without delete, message moves to DLQ"
  type        = number
  default     = 5
}

variable "tags" {
  description = "Tags for SQS queues"
  type        = map(string)
  default     = {}
}
