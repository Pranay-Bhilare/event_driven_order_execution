terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnet_ids" "default" {
  vpc_id = data.aws_vpc.default.id
}

# Security group for application EC2 instance
resource "aws_security_group" "app" {
  name        = "${var.project_name}-app-sg"
  description = "Security group for ingestion engine app"
  vpc_id      = data.aws_vpc.default.id

  # API (FastAPI)
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Prometheus / Worker metrics (optional, for testing)
  ingress {
    from_port   = 9090
    to_port     = 9091
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH access (optional, testing only)
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

# Security group for RDS PostgreSQL
resource "aws_security_group" "db" {
  name        = "${var.project_name}-db-sg"
  description = "Security group for ingestion engine RDS"
  vpc_id      = data.aws_vpc.default.id

  # Allow Postgres from app SG only
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

# EC2 instance for API + worker (Docker-based)
resource "aws_instance" "app" {
  ami                         = var.ami_id
  instance_type               = var.instance_type
  subnet_id                   = element(data.aws_subnet_ids.default.ids, 0)
  vpc_security_group_ids      = [aws_security_group.app.id]
  associate_public_ip_address = true

  key_name = var.ssh_key_name != "" ? var.ssh_key_name : null

  tags = merge(var.tags, {
    Name = "${var.project_name}-app"
  })
}

# RDS PostgreSQL instance for ingestion DB
resource "aws_db_instance" "postgres" {
  identifier = "${var.project_name}-postgres"

  engine               = "postgres"
  engine_version       = "16.3"
  instance_class       = "db.t3.micro"
  allocated_storage    = 20
  max_allocated_storage = 100

  db_name  = "ingestion"
  username = var.db_username
  password = var.db_password

  vpc_security_group_ids = [aws_security_group.db.id]

  publicly_accessible = false

  backup_retention_period = 7
  skip_final_snapshot     = true

  tags = var.tags
}

# DLQ: failed messages after max receives
resource "aws_sqs_queue" "dlq" {
  name                      = "${var.queue_name}-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = var.tags
}

# Main queue: redrive to DLQ after maxReceiveCount
resource "aws_sqs_queue" "main" {
  name                       = var.queue_name
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = 345600 # 4 days
  receive_wait_time_seconds  = 5      # long polling
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
  tags = var.tags
}
