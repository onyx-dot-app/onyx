resource "aws_db_subnet_group" "this" {
  name       = "${var.identifier}-subnet-group"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "this" {
  name        = "${var.identifier}-sg"
  description = "Allow PostgreSQL access"
  vpc_id      = var.vpc_id
  tags        = var.tags

  ingress {
    description = "Postgres ingress"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "this" {
  identifier        = var.identifier
  db_name           = var.db_name
  engine            = "postgres"
  engine_version    = var.engine_version
  instance_class    = var.instance_type
  allocated_storage = var.storage_gb
  username          = var.username
  password          = var.password

  # Enable IAM authentication for the RDS instance
  iam_database_authentication_enabled = var.enable_rds_iam_auth

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  publicly_accessible    = false
  deletion_protection    = true
  storage_encrypted      = true
  tags                   = var.tags 
}
