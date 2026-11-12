variable "onedrive_client_id" {
  description = "Microsoft Entra application client ID."
  type        = string
}

variable "onedrive_directory_id" {
  description = "Microsoft Entra directory ID."
  type        = string
}

variable "onedrive_private_key" {
  description = "Base64-encoded PKCS#12 certificate data."
  type        = string
  sensitive   = true
}

variable "onedrive_certificate_password" {
  description = "Password for the PKCS#12 certificate."
  type        = string
  sensitive   = true
}

variable "onedrive_users" {
  description = "User principal names whose OneDrive files Onyx indexes."
  type        = list(string)
}
