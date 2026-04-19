data "terraform_remote_state" "backend" {
  backend = "s3"
  config = {
    bucket = "docu-chat-ai-app-states"
    key    = "backend/${var.environment}/terraform.tfstate"
    region = var.region
  }
}