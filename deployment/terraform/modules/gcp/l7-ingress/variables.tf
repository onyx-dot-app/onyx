variable "name" {
  type        = string
  description = "Name prefix. The address and certificate map are named \"<name>-l7\", and each per-domain resource \"<name>-l7-<digest>\"."

  # "-l7-" and an 8-character digest take 12 of the 63 characters a name allows.
  validation {
    condition     = can(regex("^[a-z]([-a-z0-9]{0,49}[a-z0-9])?$", var.name))
    error_message = "name must be 1-51 characters of lowercase letters, digits and hyphens, start with a letter and not end with a hyphen."
  }
}

variable "project_id" {
  type        = string
  description = "Project that holds the address and certificates. It must be the project of the GKE cluster that runs the Gateway."

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a GCP project ID: 6-30 characters of lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "domains" {
  type        = list(string)
  description = "Hostnames the load balancer serves, for example [\"onyx.example.com\"]. Each gets a DNS authorization, a Google-managed certificate and a certificate map entry."

  validation {
    condition     = length(var.domains) > 0
    error_message = "domains must hold at least one hostname."
  }

  # Lowercase because Certificate Manager stores the domain lowercase, and a
  # mixed-case input would show a diff on every plan.
  validation {
    condition = alltrue([
      for d in var.domains :
      length(d) <= 253 && can(regex("^([a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?\\.)+[a-z]([-a-z0-9]{0,61}[a-z0-9])?$", d))
    ])
    error_message = "Each domain must be a lowercase fully qualified hostname such as onyx.example.com, with no wildcard, no trailing dot and no IP address."
  }

  validation {
    condition     = length(distinct(var.domains)) == length(var.domains)
    error_message = "domains must not repeat a hostname."
  }
}

# Losing the address means a DNS change, and a new DNS authorization can mean
# a new CNAME at the DNS provider.
variable "deletion_protection" {
  type        = bool
  description = "Make Terraform refuse to delete the address and the DNS authorizations. Set false and apply before a destroy or before you remove a domain."
  default     = true
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to every resource"
  default     = {}

  validation {
    condition = alltrue([
      for k, v in var.labels : can(regex("^[a-z][a-z0-9_-]{0,62}$", k)) && can(regex("^[a-z0-9_-]{0,63}$", v))
    ])
    error_message = "Label keys must start with a lowercase letter and contain only lowercase letters, digits, _ and -, up to 63 characters. Values follow the same rules and may be empty."
  }
}
