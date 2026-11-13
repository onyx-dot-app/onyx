package agent

// Tenant returns the tenant of a sandbox in the VM table, or "".
func (m *Manager) Tenant(sandboxID string) string {
	m.mu.Lock()
	defer m.mu.Unlock()
	if e := m.vms[sandboxID]; e != nil {
		return e.vm.TenantID
	}
	return ""
}

// Egress returns the egress set with UseEgress, or nil.
func (m *Manager) Egress() Egress { return m.egress }
