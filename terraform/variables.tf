variable "aws_region" {
  description = "AWS region for SQS queues"
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Project name prefix for AWS resources"
  type        = string
  default     = "ingestion-engine"
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

variable "db_username" {
  description = "PostgreSQL master username for RDS"
  type        = string
  default     = "postgres"
}

variable "db_password" {
  description = "PostgreSQL master password for RDS (testing only)"
  type        = string
  sensitive   = true
}

variable "instance_type" {
  description = "EC2 instance type for application"
  type        = string
  default     = "t3.micro"
}

variable "ami_id" {
  description = "AMI ID for EC2 instance (e.g. Amazon Linux in selected region)"
  type        = string
  default     = "ami-04bde106886a53080"
}

variable "ssh_key_name" {
  description = "Existing EC2 key pair name for SSH access"
  type        = string
  default     = ""
}
