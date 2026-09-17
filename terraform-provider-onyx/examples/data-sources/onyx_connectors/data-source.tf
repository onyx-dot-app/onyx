data "onyx_connectors" "all" {}

output "connector_names" {
  value = [for c in data.onyx_connectors.all.connectors : c.name]
}
