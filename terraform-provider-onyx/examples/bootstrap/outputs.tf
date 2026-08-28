output "agent_id" {
  description = "Id of the documentation agent."
  value       = onyx_persona.docs.id
}

output "cc_pair_id" {
  description = "Id of the indexing connector-credential pair."
  value       = onyx_cc_pair.docs.id
}
